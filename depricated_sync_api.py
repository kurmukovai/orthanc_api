import httplib2
import pydicom
from io import BytesIO
from functools import partial
from pydicom import dcmread, dcmwrite
from pydicom.filebase import DicomFileLike
from .RestToolbox import SetCredentials, _SetupCredentials, DoPost, DoGet
from multiprocessing import Pool
import time


def to_bytes(dcm: pydicom.dataset.FileDataset):
    """Converts dicom object to byte sequence,
    source https://pydicom.github.io/pydicom/dev/auto_examples/memory_dataset.html"""
    with BytesIO() as buffer:
        memory_dataset = DicomFileLike(buffer)  # create a DicomFileLike object that has some properties of DataSet
        dcmwrite(memory_dataset, dcm)  # write the dataset to the DicomFileLike object
        memory_dataset.seek(0)  # to read from the object, you have to rewind it
        return memory_dataset.read()  # read the contents as bytes


def from_bytes(byte_sequence):
    """Converts bytes sequence to pydicom.dataset.FileDataset."""
    return dcmread(BytesIO(byte_sequence))


def _get_instance(instance, url='http://127.0.0.1:8880'):
    """Returns instance as pydicom.dataset.FileDataset from a local dicom server."""
    return from_bytes(DoGet(f'{url}/instances/{instance}/file'))


def get_series(series, url='http://127.0.0.1:8880', n_jobs=None):
    """Returns list of instances (as pydicom.dataset.FileDataset)
     corresponding to a single series from a local dicom server."""
    instances = DoGet(f'{url}/series/{series}')['Instances']
    get_instance = partial(_get_instance, url=url)
    with Pool(n_jobs) as p:
        return p.map(get_instance, instances)


def send_series(dcm_list: list, url='http://127.0.0.1:8880', n_jobs=1):
    """Sends whole series to local dicom server"""

    h = httplib2.Http()
    SetCredentials('neuro', 'neuro')
    _SetupCredentials(h)
    url = f'{url}/instances'
    headers = {'content-type': 'application/dicom'}

    with Pool(n_jobs) as p:
        p.map(partial(_send_instance, url=url, h=h, headers=headers), dcm_list)


def _send_instance(dcm, url, h, headers):
    dcm_as_bytes = to_bytes(dcm)
    resp, content = h.request(url, 'POST', body=dcm_as_bytes, headers=headers)


def get_series_remote(patient_id, series_instance_uid,  n_jobs=2):
    """Returns all instances from series_instance_uid
         from remote dicom server."""

    source_modality = 'remote-3'
    target_modality = 'REMOTE_1'
    url = 'http://11.111.11.1111:8041'
    SetCredentials('neuro', 'neuro')

    return _get_series_remote(
        patient_id=patient_id,
        series_instance_uid=series_instance_uid,
        target_modality=target_modality,
        source_modality=source_modality,
        url=url,
        n_jobs=n_jobs)


def _get_series_remote(patient_id,  series_instance_uid,  target_modality, source_modality, url, n_jobs=1):
    """Returns all instances from patient with corresponding to series_instance_uid
     from source_modality to target_modality, hosted at url.

    ---
    Example:
    source_modality = 'remote-neuro-3'
    target_modality = 'REMOTE_1'
    patient_id = 'PATIENT_ID'
    url = 'http://127.0.0.1:8880'

    """
    query = {
        'Level': 'Series',  # Study, Series or Instance
        'Query': {
            'PatientID': patient_id}
    }
    status = DoPost(f'{url}/modalities/{source_modality}/query', data=query)
    query_id = status['ID']
    status_retrieve = DoPost(f'{url}/queries/{query_id}/retrieve', data={'TargetAet': target_modality})
    # series = list(set([result['0020,000e'] for result in status_retrieve['Query']]))

    start = time.time()
    for s in DoGet(f'{url}/series/'):
        series_query = DoGet(f'{url}/series/{s}')
        if series_query['MainDicomTags']['SeriesInstanceUID'] == series_instance_uid:
            series_orthanc_id = series_query['ID']
            dcm_list = get_series(series_orthanc_id, url, n_jobs=n_jobs)
            end = time.time()
            return dcm_list, end-start
    else:
        raise FileNotFoundError(f'No series with such SeriesInstanceUID: {series_instance_uid}')

