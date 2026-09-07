import datetime as dt
import dataclasses

from django.db import transaction

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.sync import database_sync_to_async_pool

from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobStatus, Node
from products.data_quality.backend.facade import api as data_quality_facade

from .utils import QUALITY_BLOCKED_ERROR_PREFIX, update_node_system_properties

LOGGER = get_logger(__name__)


@dataclasses.dataclass(frozen=False)
class QualityBlockMaterializationInputs:
    team_id: int
    node_id: str
    dag_id: str
    job_id: str
    blocking_failures: int
    suite_run_id: str | None = None

    @property
    def properties_to_log(self) -> dict:
        return {
            "team_id": self.team_id,
            "node_id": self.node_id,
            "dag_id": self.dag_id,
            "job_id": self.job_id,
            "blocking_failures": self.blocking_failures,
        }


def _quality_error(inputs: QualityBlockMaterializationInputs) -> str:
    checks = "check" if inputs.blocking_failures == 1 else "checks"
    return (
        f"{QUALITY_BLOCKED_ERROR_PREFIX} {inputs.blocking_failures} data quality {checks} failed. "
        "The previous version keeps serving until the checks pass."
    )


@database_sync_to_async_pool
def _block_node_and_job(inputs: QualityBlockMaterializationInputs) -> None:
    error = _quality_error(inputs)
    with transaction.atomic():
        node = Node.objects.select_for_update().get(id=inputs.node_id, team_id=inputs.team_id, dag_id=inputs.dag_id)
        update_node_system_properties(
            node,
            status=DataModelingJobStatus.FAILED,
            job_id=inputs.job_id,
            error=error,
        )
        node.save()

    job = DataModelingJob.objects.get(id=inputs.job_id)
    if job.status in (DataModelingJobStatus.FAILED, DataModelingJobStatus.CANCELLED, DataModelingJobStatus.COMPLETED):
        return
    job.status = DataModelingJobStatus.FAILED
    job.error = error
    job.last_run_at = dt.datetime.now(dt.UTC)
    job.save()

    if job.saved_query_id and node.saved_query is not None:
        data_quality_facade.notify_materialization_blocked(
            inputs.team_id, str(job.saved_query_id), node.saved_query.name, inputs.blocking_failures, inputs.job_id
        )


@activity.defn
async def quality_block_materialization_activity(inputs: QualityBlockMaterializationInputs) -> None:
    """Deliberately not ``fail_materialization_activity``: bad upstream data must not pause this
    node's schedule, revert it, or count toward suspending it.
    """
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    await _block_node_and_job(inputs)
    await logger.ainfo(
        "Materialization blocked by data quality checks",
        **inputs.properties_to_log,
    )
