from dlt.sources import DltSource

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import _get_column_hints, _get_primary_keys


def dlt_source_to_source_response(source: DltSource) -> SourceResponse:
    resources = list(source.resources.items())
    assert len(resources) == 1
    resource_name, resource = resources[0]

    return SourceResponse(
        items=resource,
        primary_keys=_get_primary_keys(resource),
        name=resource_name,
        column_hints=_get_column_hints(resource),
        partition_count=None,
    )
