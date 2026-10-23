from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from itertools import islice

from django.utils import timezone

from products.data_modeling.backend.models.data_modeling_job import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
)

# The query log reaches the archive through a buffer, so a run that has only just ended may not
# be there in full yet. A job is written only after this long, because the write happens once.
SETTLE_TIME = timedelta(minutes=15)

_TERMINAL_STATUSES = (DataModelingJobStatus.COMPLETED, DataModelingJobStatus.FAILED, DataModelingJobStatus.CANCELLED)
_BATCH_SIZE = 1000


def record_job_bytes_read(bytes_read_by_workflow_run_id: Mapping[str, int], *, finished_before: datetime) -> int:
    """Write the ClickHouse bytes read onto finished ClickHouse jobs that have none yet.

    Jobs match on ``workflow_run_id``. A job that already has a value keeps it, so a repeated
    call writes nothing new. Only jobs that stopped changing before ``finished_before`` are
    written, which is the end of the window the totals were read from, so a total never misses
    queries that ran after the window. Returns the number of jobs written.
    """
    settled_before = min(timezone.now() - SETTLE_TIME, finished_before)
    written = 0
    for batch in _batches(bytes_read_by_workflow_run_id.items()):
        values = dict(batch)
        jobs = list(
            DataModelingJob.objects.filter(
                workflow_run_id__in=values.keys(),
                engine=DataModelingJobEngine.CLICKHOUSE,
                bytes_read__isnull=True,
                status__in=_TERMINAL_STATUSES,
                updated_at__lte=settled_before,
            ).only("id", "workflow_run_id")
        )
        for job in jobs:
            if job.workflow_run_id is not None:
                job.bytes_read = values[job.workflow_run_id]
        written += DataModelingJob.objects.bulk_update(jobs, ["bytes_read"])
    return written


def _batches(items: Iterable[tuple[str, int]]) -> Iterable[list[tuple[str, int]]]:
    iterator = iter(items)
    while batch := list(islice(iterator, _BATCH_SIZE)):
        yield batch
