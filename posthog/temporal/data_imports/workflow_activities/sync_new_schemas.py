import typing as t
import dataclasses

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.sources import SourceRegistry

from products.data_warehouse.backend.models import ExternalDataSource, sync_old_schemas_with_new_schemas
from products.data_warehouse.backend.types import ExternalDataSourceType

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
async def sync_new_schemas_activity(inputs: SyncNewSchemasActivityInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    await logger.ainfo("Syncing new -> old schemas")

    @database_sync_to_async
    def _get_source_data() -> tuple[str, t.Any | None]:
        source = ExternalDataSource.objects.get(team_id=inputs.team_id, id=inputs.source_id)
        return source.source_type, source.job_inputs

    source_type, job_inputs = await _get_source_data()

    source_type_enum = ExternalDataSourceType(source_type)
    if SourceRegistry.is_registered(source_type_enum):
        if not job_inputs:
            return

        new_source = SourceRegistry.get_source(source_type_enum)
        config = new_source.parse_config(job_inputs)
        schemas = new_source.get_schemas(config, inputs.team_id)

        schemas_to_sync = [s.name for s in schemas]
    else:
        raise ValueError(f"Source type missing from SourceRegistry: {source_type}")

    # TODO: this could cause a race condition where each schema worker creates the missing schema

    @database_sync_to_async
    def _sync_schemas() -> tuple[list[str], list[str]]:
        return sync_old_schemas_with_new_schemas(
            schemas_to_sync,
            source_id=inputs.source_id,
            team_id=inputs.team_id,
        )

    schemas_created, schemas_deleted = await _sync_schemas()

    if len(schemas_created) > 0:
        await logger.ainfo(f"Added new schemas: {', '.join(schemas_created)}")
    else:
        await logger.ainfo("No new schemas to create")

    if len(schemas_deleted) > 0:
        await logger.ainfo(f"Deleted schemas: {', '.join(schemas_deleted)}")
    else:
        await logger.ainfo("No schemas to delete")
