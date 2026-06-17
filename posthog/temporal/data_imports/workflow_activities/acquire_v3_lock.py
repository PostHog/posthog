import uuid
import dataclasses
from typing import Any

from django.db import close_old_connections

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.metrics import TERMINAL_JOB_STATUSES
from posthog.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    acquire_v3_pipeline_lock,
    get_v3_pipeline_lock_holder,
    release_v3_pipeline_lock,
)
from posthog.temporal.data_imports.workflow_activities.create_job_model import is_pipeline_v3_enabled

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CheckPipelineVersionActivityInputs:
    team_id: int
    source_id: uuid.UUID


@dataclasses.dataclass(frozen=True)
class CheckPipelineVersionActivityOutputs:
    is_v3: bool


@dataclasses.dataclass
class AcquireV3LockActivityInputs:
    team_id: int
    schema_id: uuid.UUID


@dataclasses.dataclass(frozen=True)
class AcquireV3LockActivityOutputs:
    acquired: bool
    token: str


@dataclasses.dataclass
class ReleaseV3LockActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    token: str


@activity.defn
def check_pipeline_version_activity(inputs: CheckPipelineVersionActivityInputs) -> CheckPipelineVersionActivityOutputs:
    bind_contextvars(team_id=inputs.team_id)
    close_old_connections()

    try:
        source = ExternalDataSource.objects.get(id=inputs.source_id)
    except ExternalDataSource.DoesNotExist:
        return CheckPipelineVersionActivityOutputs(is_v3=False)

    is_v3 = is_pipeline_v3_enabled(inputs.team_id, source.source_type)
    return CheckPipelineVersionActivityOutputs(is_v3=is_v3)


@activity.defn
def acquire_v3_pipeline_lock_activity(inputs: AcquireV3LockActivityInputs) -> AcquireV3LockActivityOutputs:
    bind_contextvars(team_id=inputs.team_id)

    logger = LOGGER.bind()

    token = activity.info().workflow_run_id or ""
    if not token:
        logger.error("v3_pipeline_lock_missing_workflow_run_id", schema_id=str(inputs.schema_id))
        return AcquireV3LockActivityOutputs(acquired=False, token="")

    acquired = acquire_v3_pipeline_lock(inputs.team_id, str(inputs.schema_id), token)
    if not acquired:
        acquired = _take_over_lock_if_holder_finished(inputs, token, logger)

    logger.info(
        "v3_pipeline_lock_acquire_result",
        schema_id=str(inputs.schema_id),
        acquired=acquired,
        token=token,
    )

    return AcquireV3LockActivityOutputs(acquired=acquired, token=token)


def _take_over_lock_if_holder_finished(inputs: AcquireV3LockActivityInputs, token: str, logger: Any) -> bool:
    """Take over the lock when its holder's ExternalDataJob is terminal (run provably over); fail closed otherwise."""
    holder = get_v3_pipeline_lock_holder(inputs.team_id, str(inputs.schema_id))
    if holder is None:
        # Lock vanished between SET NX and GET (released or expired) — just retry.
        return acquire_v3_pipeline_lock(inputs.team_id, str(inputs.schema_id), token)

    close_old_connections()
    holder_job = (
        ExternalDataJob.objects.filter(
            team_id=inputs.team_id,
            schema_id=inputs.schema_id,
            workflow_run_id=holder,
        )
        .order_by("-created_at")
        .only("status")
        .first()
    )
    if holder_job is None or holder_job.status not in TERMINAL_JOB_STATUSES:
        return False

    logger.warning(
        "v3_pipeline_lock_taking_over_stale_lock",
        schema_id=str(inputs.schema_id),
        holder_token=holder,
        holder_job_status=holder_job.status,
    )
    release_v3_pipeline_lock(inputs.team_id, str(inputs.schema_id), holder)
    return acquire_v3_pipeline_lock(inputs.team_id, str(inputs.schema_id), token)


@activity.defn
def release_v3_pipeline_lock_activity(inputs: ReleaseV3LockActivityInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    release_v3_pipeline_lock(inputs.team_id, str(inputs.schema_id), inputs.token)
