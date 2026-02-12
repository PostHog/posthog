from dlt.sources import DltSource
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import _get_column_hints, _get_primary_keys


def dlt_source_to_source_response(source: DltSource) -> SourceResponse:
    resources = list(source.resources.items())
    assert len(resources) == 1
    resource_name, resource = resources[0]

    return SourceResponse(
        items=lambda: resource,
        primary_keys=_get_primary_keys(resource),
        name=resource_name,
        column_hints=_get_column_hints(resource),
        partition_count=None,
    )


def resolve_primary_keys(
    keys: list[str] | None,
    table_name: str,
    logger: FilteringBoundLogger,
    existing_fields: set[str] | None = None,
) -> tuple[list[str] | None, bool]:
    """Resolve primary keys for a data import source, with fallback to 'id' column.

    Returns a tuple of (primary_keys, is_id_fallback) where is_id_fallback is True
    only when no real primary keys were found and we fell back to the 'id' column.
    """
    if keys:
        logger.info(f"Found primary keys: {keys}")
        return keys, False

    if existing_fields and "id" in existing_fields:
        logger.info("Found primary keys: ['id'] (fallback)")
        return ["id"], True

    logger.warning(
        f"No primary keys found for {table_name}. If the table is not a view, "
        "(a) does the table have a primary key set? "
        "(b) does the service account have permission to read primary key metadata?"
    )
    return None, False
