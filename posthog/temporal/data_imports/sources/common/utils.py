from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import _get_column_hints, _get_primary_keys
from posthog.temporal.data_imports.sources.common.rest_source.resource import Resource


def resources_to_source_response(resources: list[Resource]) -> SourceResponse:
    assert len(resources) == 1
    resource = resources[0]

    return SourceResponse(
        items=lambda: resource,
        primary_keys=_get_primary_keys(resource),
        name=resource.name,
        column_hints=_get_column_hints(resource),
        partition_count=None,
    )


# Keep the old name as an alias for backwards compatibility during migration
dlt_source_to_source_response = resources_to_source_response
