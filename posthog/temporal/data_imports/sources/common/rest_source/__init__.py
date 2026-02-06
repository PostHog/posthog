"""Generic REST API Source - Simplified version without DLT dependency."""

from collections.abc import Callable, Iterator
from typing import Any, Optional, cast

from dateutil import parser

from .config_setup import (
    IncrementalParam,
    _bind_path_params,
    _make_endpoint_resource,
    _setup_single_entity_endpoint,
    create_auth,
    create_paginator,
    create_response_hooks,
    setup_incremental_object,
    update_dict_nested,
)
from .http_client import RESTClient
from .incremental import Incremental
from .jsonpath_utils import TJsonPath
from .pagination import BasePaginator
from .typing import ClientConfig, Endpoint, EndpointResource, EndpointResourceBase, HTTPMethodBasic, RESTAPIConfig
from .utils import exclude_keys  # noqa: F401

# Type alias for resources - simple iterators
Resource = Iterator[dict[str, Any]]


def convert_types(
    data: Iterator[Any] | list[Any], types: Optional[dict[str, dict[str, Any]]]
) -> Iterator[dict[str, Any]]:
    """Convert data types based on column configuration."""
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


def rest_api_resources(
    config: RESTAPIConfig, team_id: int, job_id: str, db_incremental_field_last_value: Optional[Any]
) -> Resource:
    """Creates a resource iterator from a REST API configuration.

    Args:
        config: Configuration with single resource in "resources" array
        team_id: Team ID
        job_id: Job ID
        db_incremental_field_last_value: Last incremental value from database

    Returns:
        Resource iterator yielding dicts
    """
    client_config = config["client"]
    resource_defaults: EndpointResourceBase = config.get("resource_defaults", {})
    resource_list = config["resources"]

    resources = create_resources(
        client_config,
        resource_defaults,
        resource_list,
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )

    # Return first resource (we only use single resources in production)
    return next(iter(resources.values()))


def create_resources(
    client_config: ClientConfig,
    resource_defaults: EndpointResourceBase,
    resource_list: list[str | EndpointResource],
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any] = None,
) -> dict[str, Resource]:
    """Create resource iterators from configuration.

    Simplified version without dependency graph support.
    """
    resources = {}

    # Process each resource
    for resource_kwargs in resource_list:
        if isinstance(resource_kwargs, dict):
            resource_kwargs = cast(EndpointResource, update_dict_nested({}, dict(resource_kwargs)))

        endpoint_resource = _make_endpoint_resource(resource_kwargs, resource_defaults)
        assert isinstance(endpoint_resource["endpoint"], dict)
        _setup_single_entity_endpoint(endpoint_resource["endpoint"])
        _bind_path_params(endpoint_resource)

        resource_name = endpoint_resource["name"]
        assert isinstance(resource_name, str), f"Resource name must be a string, got {type(resource_name)}"

        endpoint_config = cast(Endpoint, endpoint_resource.get("endpoint"))
        request_params = endpoint_config.get("params", {})
        request_json = endpoint_config.get("json", None)
        paginator = create_paginator(endpoint_config.get("paginator"))

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
        columns_config_raw = endpoint_resource.get("columns")
        columns_config: Optional[dict[str, dict[str, Any]]] = (
            columns_config_raw if isinstance(columns_config_raw, dict) else None
        )

        # Create resource generator
        def make_resource(
            method: HTTPMethodBasic,
            path: str,
            params: dict[str, Any],
            json_body: Optional[dict[str, Any]],
            paginator: Optional[BasePaginator],
            data_selector: Optional[TJsonPath],
            hooks: Optional[dict[str, Any]],
            client: RESTClient,
            columns_config: Optional[dict[str, dict[str, Any]]],
            incremental_object: Optional[Incremental],
            incremental_param: Optional[IncrementalParam],
            incremental_cursor_transform: Optional[Callable[..., Any]],
            db_incremental_field_last_value: Optional[Any],
        ) -> Resource:
            """Generator function for resource data."""
            # Set up incremental params
            if incremental_object:
                params = _set_incremental_params(
                    params,
                    incremental_object,
                    incremental_param,
                    incremental_cursor_transform,
                    db_incremental_field_last_value,
                )

            # Paginate and yield data
            yield from convert_types(
                client.paginate(
                    method=method,
                    path=path,
                    params=params,
                    json=json_body,
                    data_selector=data_selector,
                ),
                columns_config,
            )

        # Store resource with its hints for later use
        resource = make_resource(
            method=endpoint_config.get("method", "GET"),  # type: ignore[arg-type]
            path=endpoint_config.get("path"),  # type: ignore[arg-type]
            params=request_params.copy() if request_params else {},
            json_body=request_json,
            paginator=paginator,
            data_selector=endpoint_config.get("data_selector"),
            hooks=hooks,
            client=client,
            columns_config=columns_config,
            incremental_object=incremental_object,
            incremental_param=incremental_param,
            incremental_cursor_transform=incremental_cursor_transform,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

        # No need to attach hints - not using DLT anymore
        resources[resource_name] = resource

    return resources


def _set_incremental_params(
    params: dict[str, Any],
    incremental_object: Incremental,
    incremental_param: Optional[IncrementalParam],
    transform: Optional[Callable[..., Any]],
    db_incremental_field_last_value: Optional[Any] = None,
) -> dict[str, Any]:
    """Set incremental parameters in request params."""

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
