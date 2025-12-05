from collections.abc import Sequence

from dlt.common.data_types.typing import TDataType
from dlt.sources import DltResource, DltSource

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import normalize_column_name


def _get_column_hints(resource: DltResource) -> dict[str, TDataType | None] | None:
    columns = resource._hints.get("columns")
    if columns is None:
        return None
    return {key: value.get("data_type") for key, value in columns.items()}  # type: ignore


def _get_primary_keys(resource: DltResource) -> list[str] | None:
    primary_keys = resource._hints.get("primary_key")
    if primary_keys is None:
        return None
    if isinstance(primary_keys, str):
        return [normalize_column_name(primary_keys)]
    if isinstance(primary_keys, list | Sequence):
        return [normalize_column_name(pk) for pk in primary_keys]
    raise Exception(f"primary_keys of type {primary_keys.__class__.__name__} are not supported")


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
