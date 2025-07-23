import dataclasses
import typing as t

from django.db import close_old_connections
from temporalio import activity

from posthog.temporal.common.logger import bind_temporal_worker_logger_sync
from posthog.warehouse.models import (
    ExternalDataSource,
    sync_old_schemas_with_new_schemas,
)

from posthog.temporal.data_imports.sources import SourceRegistry


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
    logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)
    close_old_connections()

    logger.info("Syncing new -> old schemas")

    source = ExternalDataSource.objects.get(team_id=inputs.team_id, id=inputs.source_id)

    source_type_enum = ExternalDataSource.Type(source.source_type)
    if SourceRegistry.is_registered(source_type_enum):
        if not source.job_inputs:
            return

        new_source = SourceRegistry.get_source(source_type_enum)
        config = new_source.parse_config(source.job_inputs)
        schemas = new_source.get_schemas(config, inputs.team_id)

        schemas_to_sync = [s.name for s in schemas]

    # TODO: this could cause a race condition where each schema worker creates the missing schema

    schemas_created = sync_old_schemas_with_new_schemas(
        schemas_to_sync,
        source_id=inputs.source_id,
        team_id=inputs.team_id,
    )

    if len(schemas_created) > 0:
        logger.info(f"Added new schemas: {', '.join(schemas_created)}")
    else:
        logger.info("No new schemas to create")
