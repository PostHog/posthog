import uuid
import dataclasses

from django.db import close_old_connections

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    acquire_v3_pipeline_lock,
    release_v3_pipeline_lock,
)
from posthog.temporal.data_imports.workflow_activities.create_job_model import _is_pipeline_v3_enabled

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class AcquireV3LockActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID


@dataclasses.dataclass(frozen=True)
class AcquireV3LockActivityOutputs:
    acquired: bool
    is_v3: bool
    token: str


@dataclasses.dataclass
class ReleaseV3LockActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    token: str


@activity.defn
def acquire_v3_pipeline_lock_activity(inputs: AcquireV3LockActivityInputs) -> AcquireV3LockActivityOutputs:
    bind_contextvars(team_id=inputs.team_id)
    close_old_connections()

    logger = LOGGER.bind()

    try:
        source = ExternalDataSource.objects.get(id=inputs.source_id)
    except ExternalDataSource.DoesNotExist:
        return AcquireV3LockActivityOutputs(acquired=True, is_v3=False, token="")

    if not _is_pipeline_v3_enabled(inputs.team_id, source.source_type):
        return AcquireV3LockActivityOutputs(acquired=True, is_v3=False, token="")

    token = activity.info().workflow_run_id or ""
    if not token:
        return AcquireV3LockActivityOutputs(acquired=True, is_v3=True, token="")

    acquired = acquire_v3_pipeline_lock(inputs.team_id, str(inputs.schema_id), token)

    logger.info(
        "v3_pipeline_lock_acquire_result",
        schema_id=str(inputs.schema_id),
        acquired=acquired,
        token=token,
    )

    return AcquireV3LockActivityOutputs(acquired=acquired, is_v3=True, token=token)


@activity.defn
def release_v3_pipeline_lock_activity(inputs: ReleaseV3LockActivityInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    release_v3_pipeline_lock(inputs.team_id, str(inputs.schema_id), inputs.token)
