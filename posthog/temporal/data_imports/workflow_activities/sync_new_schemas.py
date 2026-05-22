import typing as t
import dataclasses

from django.db import close_old_connections

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.external_data_job import Any_Source_Errors
from posthog.temporal.data_imports.sources import SourceRegistry
from posthog.temporal.data_imports.util import NonRetryableException

from products.data_warehouse.backend.data_load.service import delete_discover_schemas_schedule
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.warehouse_sources.backend.models.external_data_schema import sync_old_schemas_with_new_schemas
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class SyncNewSchemasActivityInputs:
    source_id: str
    team_id: int

    @property
    def properties_to_log(self) -> dict[str, t.Any]:
        return {
            "source_id": self.source_id,
            "team_id": self.team_id,
        }


@activity.defn
def sync_new_schemas_activity(inputs: SyncNewSchemasActivityInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    close_old_connections()

    logger.info("Syncing new -> old schemas")

    # Self-destruct: if the source has been deleted (or hard-removed) since the schedule
    # was created, drop the discovery schedule so we stop firing zombie workflows. Mirrors
    # the existing per-schema pattern in `create_external_data_job_model_activity`.
    source_exists = (
        ExternalDataSource.objects.filter(team_id=inputs.team_id, id=inputs.source_id).exclude(deleted=True).exists()
    )
    if not source_exists:
        delete_discover_schemas_schedule(str(inputs.source_id))
        raise Exception("Source no longer exists - deleted discover-schemas temporal schedule")

    source = ExternalDataSource.objects.get(team_id=inputs.team_id, id=inputs.source_id)

    source_type_enum = ExternalDataSourceType(source.source_type)
    if SourceRegistry.is_registered(source_type_enum):
        if not source.job_inputs:
            return

        new_source = SourceRegistry.get_source(source_type_enum)
        config = new_source.parse_config(source.job_inputs)
        try:
            schemas = new_source.get_schemas(config, inputs.team_id)
        except Exception as e:
            # Mirror the per-schema sync path in `import_data_sync._run` so user-configuration
            # errors (bad host, DNS, wrong creds, …) short-circuit the discovery workflow
            # instead of surfacing as retried failures in error tracking.
            non_retryable_errors = {**Any_Source_Errors, **new_source.get_non_retryable_errors()}
            error_msg = str(e)
            if any(pattern in error_msg for pattern in non_retryable_errors):
                logger.info(f"Non-retryable error during schema discovery: {error_msg}")
                raise NonRetryableException(error_msg) from e
            raise

        schemas_to_sync = {s.name: s.label for s in schemas}
    else:
        raise ValueError(f"Source type missing from SourceRegistry: {source.source_type}")

    # TODO: this could cause a race condition where each schema worker creates the missing schema

    schemas_created, schemas_deleted = sync_old_schemas_with_new_schemas(
        schemas_to_sync,
        source_id=inputs.source_id,
        team_id=inputs.team_id,
    )

    if len(schemas_created) > 0:
        logger.info(f"Added new schemas: {', '.join(schemas_created)}")
    else:
        logger.info("No new schemas to create")

    if len(schemas_deleted) > 0:
        logger.info(f"Deleted schemas: {', '.join(schemas_deleted)}")
    else:
        logger.info("No schemas to delete")
