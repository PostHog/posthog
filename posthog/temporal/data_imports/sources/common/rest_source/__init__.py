"""Generic API Source"""

import graphlib  # type: ignore[import,unused-ignore]
from collections.abc import Callable, Iterator
from typing import Any, Optional, cast

from dateutil import parser

from .config_setup import (
    Incremental,
    IncrementalParam,
    build_resource_dependency_graph,
    create_auth,
    create_paginator,
    create_response_hooks,
    process_parent_data_item,
    setup_incremental_object,
)
from .jsonpath_utils import TJsonPath
from .paginators import BasePaginator
from .resource import Resource
from .rest_client import RESTClient
from .typing import ClientConfig, Endpoint, EndpointResource, HTTPMethodBasic, ResolvedParam, RESTAPIConfig
from .utils import exclude_keys  # noqa: F401


def convert_types(
    data: Iterator[Any] | list[Any], types: Optional[dict[str, dict[str, Any]]]
) -> Iterator[dict[str, Any]]:
    if types is None:
        yield from data
        return

    for item in data:
        for key, column in types.items():
            data_type = column.get("data_type")

            if key in item:
                current_value = item.get(key)
                if data_type == "timestamp" and isinstance(current_value, str):
                    item[key] = parser.parse(current_value)
                elif data_type == "date" and isinstance(current_value, str):
                    item[key] = parser.parse(current_value).date()

        yield item


def rest_api_resource(
    config: RESTAPIConfig, team_id: int, job_id: str, db_incremental_field_last_value: Optional[Any]
) -> Resource:
    """Creates a single resource from a REST API configuration.

    Most sources define exactly one resource. Use ``rest_api_resources``
    (plural) only when the config contains multiple resources (e.g. date
    chunked report endpoints or parent/child fanout).
    """
    resources = rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)
    assert len(resources) == 1, f"Expected 1 resource, got {len(resources)}"
    return resources[0]


def rest_api_resources(
    config: RESTAPIConfig, team_id: int, job_id: str, db_incremental_field_last_value: Optional[Any]
) -> list[Resource]:
    """Creates a list of resources from a REST API configuration.

    Prefer ``rest_api_resource`` (singular) for the common single-resource
    case. This function is needed for multi-resource configs like date-chunked
    report endpoints or parent/child fanout.
    """
    client_config = config["client"]
    resource_defaults = config.get("resource_defaults") or {}
    resource_list = config["resources"]

    (
        dependency_graph,
        endpoint_resource_map,
        resolved_param_map,
    ) = build_resource_dependency_graph(
        resource_defaults,
        resource_list,
    )

    resources = create_resources(
        client_config,
        dependency_graph,
        endpoint_resource_map,
        resolved_param_map,
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )

    return list(resources.values())


def _make_paginate_dependent_resource(
    *,
    client: RESTClient,
    resolved_param: ResolvedParam,
    include_from_parent: list[str],
    default_columns_config: Optional[Any],
    incremental_object: Optional[Incremental],
    incremental_param: Optional[IncrementalParam],
    incremental_cursor_transform: Optional[Callable[..., Any]],
    db_incremental_field_last_value: Optional[Any],
) -> Callable[..., Iterator[list[Any]]]:
    """Build the generator for a dependent (child) resource."""

    def paginate_dependent_resource(
        items: list[dict[str, Any]],
        method: HTTPMethodBasic,
        path: str,
        params: dict[str, Any],
        paginator: Optional[BasePaginator],
        data_selector: Optional[TJsonPath],
        hooks: Optional[dict[str, Any]],
        columns_config: Optional[Any] = None,
    ) -> Iterator[list[Any]]:
        effective_columns_config = columns_config if columns_config is not None else default_columns_config

        if incremental_object:
            params = _set_incremental_params(
                params,
                incremental_object,
                incremental_param,
                incremental_cursor_transform,
                db_incremental_field_last_value,
            )

        for item in items:
            formatted_path, parent_record = process_parent_data_item(path, item, resolved_param, include_from_parent)

            for child_page in client.paginate(
                method=method,
                path=formatted_path,
                params=dict(params),
                paginator=paginator,
                data_selector=data_selector,
                hooks=hooks,
            ):
                if parent_record:
                    for child_record in child_page:
                        child_record.update(parent_record)

                yield list(convert_types(child_page, effective_columns_config))

    return paginate_dependent_resource


def create_resources(
    client_config: ClientConfig,
    dependency_graph: graphlib.TopologicalSorter,
    endpoint_resource_map: dict[str, EndpointResource],
    resolved_param_map: dict[str, Optional[ResolvedParam]],
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any] = None,
) -> dict[str, Resource]:
    resources: dict[str, Resource] = {}

    for resource_name in dependency_graph.static_order():
        resource_name = cast(str, resource_name)
        endpoint_resource = endpoint_resource_map[resource_name]
        endpoint_config = cast(Endpoint, endpoint_resource.get("endpoint"))
        request_params = endpoint_config.get("params") or {}
        request_json = endpoint_config.get("json", None)
        paginator = create_paginator(endpoint_config.get("paginator"))

        resolved_param: ResolvedParam | None = resolved_param_map[resource_name]

        include_from_parent: list[str] = endpoint_resource.get("include_from_parent") or []
        if not resolved_param and include_from_parent:
            raise ValueError(
                f"Resource {resource_name} has include_from_parent but is not dependent on another resource"
            )

        (
            incremental_object,
            incremental_param,
            incremental_cursor_transform,
        ) = setup_incremental_object(request_params, endpoint_config.get("incremental"))

        client = RESTClient(
            base_url=client_config.get("base_url"),
            headers=client_config.get("headers"),
            auth=create_auth(client_config.get("auth")),
            paginator=create_paginator(client_config.get("paginator")),
        )

        hooks = create_response_hooks(endpoint_config.get("response_actions"))

        resource_kwargs = exclude_keys(endpoint_resource, {"endpoint", "include_from_parent"})

        columns_config = endpoint_resource.get("columns")

        hints = {
            k: v
            for k, v in resource_kwargs.items()
            if k
            in (
                "columns",
                "write_disposition",
                "table_name",
                "table_format",
                "merge_key",
                "schema_contract",
            )
        }

        if resolved_param is None:

            def paginate_resource(
                method: HTTPMethodBasic,
                path: str,
                params: dict[str, Any],
                json: Optional[dict[str, Any]],
                paginator: Optional[BasePaginator],
                data_selector: Optional[TJsonPath],
                hooks: Optional[dict[str, Any]],
                client: RESTClient = client,
                columns_config: Optional[Any] = None,
                incremental_object: Optional[Incremental] = incremental_object,
                incremental_param: Optional[IncrementalParam] = incremental_param,
                incremental_cursor_transform: Optional[Callable[..., Any]] = incremental_cursor_transform,
            ) -> Iterator[list[Any]]:
                if incremental_object:
                    params = _set_incremental_params(
                        params,
                        incremental_object,
                        incremental_param,
                        incremental_cursor_transform,
                        db_incremental_field_last_value,
                    )

                for page in client.paginate(
                    method=method,
                    path=path,
                    params=params,
                    json=json,
                    paginator=paginator,
                    data_selector=data_selector,
                    hooks=hooks,
                ):
                    yield list(convert_types(page, columns_config))

            resources[resource_name] = Resource(
                paginate_resource,
                name=resource_name,
                hints=hints,
                kwargs={
                    "method": endpoint_config.get("method", "get"),
                    "path": endpoint_config.get("path"),
                    "params": request_params,
                    "json": request_json,
                    "paginator": paginator,
                    "data_selector": endpoint_config.get("data_selector"),
                    "hooks": hooks,
                    "columns_config": columns_config,
                },
            )

        else:
            predecessor = resources[resolved_param.resolve_config["resource"]]

            base_params = exclude_keys(request_params, {resolved_param.param_name})

            paginate_fn = _make_paginate_dependent_resource(
                client=client,
                resolved_param=resolved_param,
                include_from_parent=include_from_parent,
                default_columns_config=columns_config,
                incremental_object=incremental_object,
                incremental_param=incremental_param,
                incremental_cursor_transform=incremental_cursor_transform,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )

            resources[resource_name] = Resource(
                paginate_fn,
                name=resource_name,
                hints=hints,
                kwargs={
                    # ``items`` is injected per parent page by Resource.__iter__
                    # when ``data_from`` is set.
                    "method": endpoint_config.get("method", "get"),
                    "path": endpoint_config.get("path"),
                    "params": base_params,
                    "paginator": paginator,
                    "data_selector": endpoint_config.get("data_selector"),
                    "hooks": hooks,
                    "columns_config": columns_config,
                },
                data_from=predecessor,
            )

    return resources


def _set_incremental_params(
    params: dict[str, Any],
    incremental_object: Incremental,
    incremental_param: Optional[IncrementalParam],
    transform: Optional[Callable[..., Any]],
    db_incremental_field_last_value: Optional[Any] = None,
) -> dict[str, Any]:
    def identity_func(x: Any) -> Any:
        return x

    if transform is None:
        transform = identity_func

    if incremental_param is None:
        return params

    last_value = (
        db_incremental_field_last_value
        if db_incremental_field_last_value is not None
        else incremental_object.last_value
    )

    params[incremental_param.start] = transform(last_value)
    if incremental_param.end:
        params[incremental_param.end] = transform(incremental_object.end_value)
    return params
