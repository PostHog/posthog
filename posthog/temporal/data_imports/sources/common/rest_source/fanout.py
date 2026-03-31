from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)


class FanoutEndpointLike(Protocol):
    name: str
    path: str
    incremental_fields: list[Any]
    default_incremental_field: str | None
    page_size: int
    primary_key: str | list[str]


@dataclass(frozen=True)
class DependentEndpointConfig:
    parent_name: str
    resolve_param: str
    resolve_field: str
    include_from_parent: list[str]
    parent_field_renames: dict[str, str] = field(default_factory=dict)
    parent_params: dict[str, Any] = field(default_factory=dict)


def rename_parent_fields(parent_name: str, renames: dict[str, str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    if not renames:
        return lambda row: row

    key_map = {f"_{parent_name}_{src}": dst for src, dst in renames.items()}

    def _mapper(row: dict[str, Any]) -> dict[str, Any]:
        for prefixed_key, target_key in key_map.items():
            if prefixed_key in row:
                row[target_key] = row.pop(prefixed_key)
        return row

    return _mapper


def build_dependent_resource(
    *,
    endpoint_configs: Mapping[str, FanoutEndpointLike],
    child_endpoint: str,
    fanout: DependentEndpointConfig,
    client_config: ClientConfig,
    path_format_values: dict[str, str],
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Any,
    should_use_incremental_field: bool = False,
    incremental_field: str | None = None,
    incremental_config_factory: Callable[[str], IncrementalConfig] | None = None,
    parent_endpoint_extra: Endpoint | None = None,
    child_endpoint_extra: Endpoint | None = None,
    page_size_param: str = "limit",
) -> Iterable[Any]:
    parent_config = endpoint_configs[fanout.parent_name]
    child_config = endpoint_configs[child_endpoint]

    parent_params: dict[str, Any] = {page_size_param: parent_config.page_size}
    parent_params.update(fanout.parent_params)

    parent_path = parent_config.path
    for key, value in path_format_values.items():
        parent_path = parent_path.replace(f"{{{key}}}", value)

    parent_endpoint_config: Endpoint = {
        "path": parent_path,
        "params": parent_params,
    }
    if parent_endpoint_extra:
        if "params" in parent_endpoint_extra:
            raise ValueError(
                "Do not pass 'params' in parent_endpoint_extra. Use fanout.parent_params or page_size_param instead."
            )
        parent_endpoint_config.update(parent_endpoint_extra)

    parent_resource: EndpointResource = {
        "name": fanout.parent_name,
        "table_name": fanout.parent_name,
        "primary_key": parent_config.primary_key,
        "write_disposition": "replace",
        "endpoint": parent_endpoint_config,
        "table_format": "delta",
    }

    child_path = child_config.path
    for key, value in path_format_values.items():
        child_path = child_path.replace(f"{{{key}}}", value)

    child_params: dict[str, Any] = {
        fanout.resolve_param: {
            "type": "resolve",
            "resource": fanout.parent_name,
            "field": fanout.resolve_field,
        },
        page_size_param: child_config.page_size,
    }
    child_endpoint_config: Endpoint = {
        "path": child_path,
        "params": child_params,
    }
    if child_endpoint_extra:
        if "params" in child_endpoint_extra:
            raise ValueError(
                "Do not pass 'params' in child_endpoint_extra. "
                "The child resolve/page-size params are managed by build_dependent_resource."
            )
        child_endpoint_config.update(child_endpoint_extra)

    use_merge = should_use_incremental_field and bool(child_config.incremental_fields)
    if use_merge:
        if incremental_config_factory is None:
            raise ValueError("incremental_config_factory is required for incremental fan-out resources")
        child_endpoint_config["incremental"] = incremental_config_factory(
            incremental_field or child_config.default_incremental_field or "id"
        )

    child_resource: EndpointResource = {
        "name": child_endpoint,
        "table_name": child_endpoint,
        "primary_key": child_config.primary_key,
        "write_disposition": ({"disposition": "merge", "strategy": "upsert"} if use_merge else "replace"),
        "include_from_parent": fanout.include_from_parent,
        "endpoint": child_endpoint_config,
        "table_format": "delta",
    }

    config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [parent_resource, child_resource],
    }

    resources = rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)
    child_dlt_resource = next(r for r in resources if getattr(r, "name", None) == child_endpoint)
    return child_dlt_resource.add_map(rename_parent_fields(fanout.parent_name, fanout.parent_field_renames))
