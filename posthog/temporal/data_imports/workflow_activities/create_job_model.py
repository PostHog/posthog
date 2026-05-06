import uuid
import typing
import dataclasses
from typing import Any

from django.db import close_old_connections

import posthoganalytics
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.signals.registry import get_signal_source_identity

from products.data_warehouse.backend.data_load.service import delete_external_data_schedule
from products.data_warehouse.backend.models import ExternalDataJob, ExternalDataSource
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.signals.backend.models import SignalSourceConfig

WAREHOUSE_PIPELINES_V3_FLAG = "warehouse-pipelines-v3"


def _is_pipeline_v3_enabled(team_id: int, source_type: str) -> bool:
    try:
        team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    except Team.DoesNotExist:
        return False

    try:
        return bool(
            posthoganalytics.feature_enabled(
                WAREHOUSE_PIPELINES_V3_FLAG,
                str(team.uuid),
                groups={
                    "organization": str(team.organization_id),
                    "project": str(team.id),
                },
                group_properties={
                    "organization": {"id": str(team.organization_id), "source_type": source_type},
                    "project": {"id": str(team.id), "source_type": source_type},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        capture_exception(e)
        return False


LOGGER = get_logger(__name__)


def _build_schema_snapshot(schema: ExternalDataSchema) -> dict[str, Any]:
    return {
        "name": schema.name,
        "sync_type": schema.sync_type,
        "sync_type_config": schema.sync_type_config,
        "sync_frequency_interval": schema.sync_frequency_interval.total_seconds()
        if schema.sync_frequency_interval
        else None,
        "should_sync": schema.should_sync,
        "status": schema.status,
        "last_synced_at": schema.last_synced_at.isoformat() if schema.last_synced_at else None,
        "initial_sync_complete": schema.initial_sync_complete,
    }


# TODO: remove dependency


@dataclasses.dataclass
class CreateExternalDataJobModelActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID
    billable: bool

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "schema_id": self.schema_id,
            "source_id": self.source_id,
            "billable": self.billable,
        }


@dataclasses.dataclass(frozen=True)
class CreateExternalDataJobModelActivityOutputs:
    job_id: str
    incremental_or_append: bool
    source_type: str
    schema_name: str
    # ISO timestamp of when the previous sync completed, used to detect new records
    last_synced_at: str | None = None
    emit_signals_enabled: bool = False


@activity.defn
def create_external_data_job_model_activity(
    inputs: CreateExternalDataJobModelActivityInputs,
) -> CreateExternalDataJobModelActivityOutputs:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    close_old_connections()

    try:
        source_exists = ExternalDataSource.objects.filter(id=inputs.source_id).exclude(deleted=True).exists()
        schema_exists = ExternalDataSchema.objects.filter(id=inputs.schema_id).exclude(deleted=True).exists()

        if not source_exists or not schema_exists:
            delete_external_data_schedule(str(inputs.schema_id))
            raise Exception("Source or schema no longer exists - deleted temporal schedule")

        schema = ExternalDataSchema.objects.get(team_id=inputs.team_id, id=inputs.schema_id)
        schema.status = ExternalDataSchema.Status.RUNNING
        schema.save()

        source: ExternalDataSource = schema.source

        pipeline_version = ExternalDataJob.PipelineVersion.V2
        if _is_pipeline_v3_enabled(inputs.team_id, source.source_type):
            pipeline_version = ExternalDataJob.PipelineVersion.V3

        job = ExternalDataJob.objects.create(
            team_id=inputs.team_id,
            pipeline_id=inputs.source_id,
            schema_id=inputs.schema_id,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            workflow_id=activity.info().workflow_id,
            workflow_run_id=activity.info().workflow_run_id,
            pipeline_version=pipeline_version,
            billable=inputs.billable,
            schema_snapshot=_build_schema_snapshot(schema),
        )

        logger.info(
            f"Created external data job for external data source {inputs.source_id}",
        )

        # Check if signals should be emitted: AI consent + SignalSourceConfig enabled for this source
        signal_identity = get_signal_source_identity(source.source_type, schema.name)
        emit_signals_enabled = False
        if signal_identity is not None:
            signal_source_product, signal_source_type = signal_identity
            team = (
                Team.objects.filter(id=inputs.team_id)
                .select_related("organization")
                .only("organization__is_ai_data_processing_approved")
                .first()
            )
            if team is not None and team.organization.is_ai_data_processing_approved is True:
                emit_signals_enabled = SignalSourceConfig.objects.filter(
                    team_id=inputs.team_id,
                    source_product=signal_source_product,
                    source_type=signal_source_type,
                    enabled=True,
                ).exists()

        return CreateExternalDataJobModelActivityOutputs(
            job_id=str(job.id),
            incremental_or_append=schema.is_incremental or schema.is_append or schema.is_webhook,
            source_type=source.source_type,
            schema_name=schema.name,
            last_synced_at=schema.last_synced_at.isoformat() if schema.last_synced_at else None,
            emit_signals_enabled=emit_signals_enabled,
        )
    except Exception as e:
        logger.exception(
            f"External data job failed on create_external_data_job_model_activity for {str(inputs.source_id)} with error: {e}"
        )
        raise
