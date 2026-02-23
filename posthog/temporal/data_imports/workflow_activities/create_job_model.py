import uuid
import typing
import dataclasses

from django.db import close_old_connections

import posthoganalytics
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.models.organization import Organization
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.signals import EMIT_SIGNALS_FEATURE_FLAG, is_signal_emission_registered

from products.data_warehouse.backend.data_load.service import delete_external_data_schedule
from products.data_warehouse.backend.models import ExternalDataJob, ExternalDataSource
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

LOGGER = get_logger(__name__)

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

        job = ExternalDataJob.objects.create(
            team_id=inputs.team_id,
            pipeline_id=inputs.source_id,
            schema_id=inputs.schema_id,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            workflow_id=activity.info().workflow_id,
            workflow_run_id=activity.info().workflow_run_id,
            pipeline_version=ExternalDataJob.PipelineVersion.V2,
            billable=inputs.billable,
        )

        schema = ExternalDataSchema.objects.get(team_id=inputs.team_id, id=inputs.schema_id)
        schema.status = ExternalDataSchema.Status.RUNNING
        schema.save()

        source: ExternalDataSource = schema.source

        logger.info(
            f"Created external data job for external data source {inputs.source_id}",
        )

        # Cheap check if to start signals workflow to avoid spawning it for all teams.
        # AI consent + Signals FF + source supported
        ai_consent = (
            Organization.objects.filter(team__id=inputs.team_id)
            .values_list("is_ai_data_processing_approved", flat=True)
            .first()
        )
        emit_signals_enabled = (
            ai_consent is True
            and is_signal_emission_registered(source.source_type, schema.name)
            and posthoganalytics.feature_enabled(EMIT_SIGNALS_FEATURE_FLAG, str(inputs.team_id)) is True
        )

        return CreateExternalDataJobModelActivityOutputs(
            job_id=str(job.id),
            incremental_or_append=schema.is_incremental or schema.is_append,
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
