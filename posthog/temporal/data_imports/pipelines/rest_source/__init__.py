"""Generic API Source"""

from typing import (
    Any,
    Optional,
    cast,
)
from collections.abc import AsyncGenerator, Iterator
from collections.abc import Callable
import graphlib  # type: ignore[import,unused-ignore]

import dlt
from dlt.common.validation import validate_dict
from dlt.common import jsonpath
from dlt.common.schema.schema import Schema
from dlt.common.schema.typing import TSchemaContract
from dlt.common.configuration.specs import BaseConfiguration

from dlt.extract.incremental import Incremental
from dlt.extract.source import DltResource, DltSource

from dlt.sources.helpers.rest_client.client import RESTClient
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from dlt.sources.helpers.rest_client.typing import HTTPMethodBasic

from .typing import (
    ClientConfig,
    ResolvedParam,
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
)
from .config_setup import (
    IncrementalParam,
    create_auth,
    create_paginator,
    build_resource_dependency_graph,
    process_parent_data_item,
    setup_incremental_object,
    create_response_hooks,
)
from .utils import exclude_keys  # noqa: F401


def rest_api_source(
    config: RESTAPIConfig,
    team_id: int,
    job_id: str,
    name: Optional[str] = None,
    section: Optional[str] = None,
    max_table_nesting: Optional[int] = None,
    root_key: bool = False,
    schema: Optional[Schema] = None,
    schema_contract: Optional[TSchemaContract] = None,
    spec: Optional[type[BaseConfiguration]] = None,
) -> DltSource:
    """Creates and configures a REST API source for data extraction.

    Args:
        config (RESTAPIConfig): Configuration for the REST API source.
        name (str, optional): Name of the source.
        section (str, optional): Section of the configuration file.
        max_table_nesting (int, optional): Maximum depth of nested table above which
            the remaining nodes are loaded as structs or JSON.
        root_key (bool, optional): Enables merging on all resources by propagating
            root foreign key to child tables. This option is most useful if you
            plan to change write disposition of a resource to disable/enable merge.
            Defaults to False.
        schema (Schema, optional): An explicit `Schema` instance to be associated
            with the source. If not present, `dlt` creates a new `Schema` object
            with provided `name`. If such `Schema` already exists in the same
            folder as the module containing the decorated function, such schema
            will be loaded from file.
        schema_contract (TSchemaContract, optional): Schema contract settings
            that will be applied to this resource.
        spec (type[BaseConfiguration], optional): A specification of configuration
            and secret values required by the source.

    Returns:
        DltSource: A configured dlt source.

    Example:
        pokemon_source = rest_api_source({
            "client": {
                "base_url": "https://pokeapi.co/api/v2/",
                "paginator": "json_response",
            },
            "endpoints": {
                "pokemon": {
                    "params": {
                        "limit": 100, # Default page size is 20
                    },
                    "resource": {
                        "primary_key": "id",
                    }
                },
            },
        })
    """
    decorated = dlt.source(
        rest_api_resources,
        name,
        section,
        max_table_nesting,
        root_key,
        schema,
        schema_contract,
        spec,
    )

    return decorated(config, team_id, job_id)


def rest_api_resources(config: RESTAPIConfig, team_id: int, job_id: str) -> list[DltResource]:
    """Creates a list of resources from a REST API configuration.

    Args:
        config (RESTAPIConfig): Configuration for the REST API source.

    Returns:
        list[DltResource]: List of dlt resources.

    Example:
        github_source = rest_api_resources({
            "client": {
                "base_url": "https://api.github.com/repos/dlt-hub/dlt/",
                "auth": {
                    "token": dlt.secrets["token"],
                },
            },
            "resource_defaults": {
                "primary_key": "id",
                "write_disposition": "merge",
                "endpoint": {
                    "params": {
                        "per_page": 100,
                    },
                },
            },
            "resources": [
                {
                    "name": "issues",
                    "endpoint": {
                        "path": "issues",
                        "params": {
                            "sort": "updated",
                            "direction": "desc",
                            "state": "open",
                            "since": {
                                "type": "incremental",
                                "cursor_path": "updated_at",
                                "initial_value": "2024-01-25T11:21:28Z",
                            },
                        },
                    },
                },
                {
                    "name": "issue_comments",
                    "endpoint": {
                        "path": "issues/{issue_number}/comments",
                        "params": {
                            "issue_number": {
                                "type": "resolve",
                                "resource": "issues",
                                "field": "number",
                            }
                        },
                    },
                },
            ],
        })
    """

    validate_dict(RESTAPIConfig, config, path=".")

    client_config = config["client"]
    resource_defaults = config.get("resource_defaults", {})
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
    )

    return list(resources.values())


def create_resources(
    client_config: ClientConfig,
    dependency_graph: graphlib.TopologicalSorter,
    endpoint_resource_map: dict[str, EndpointResource],
    resolved_param_map: dict[str, Optional[ResolvedParam]],
    team_id: int,
    job_id: str,
) -> dict[str, DltResource]:
    resources = {}

    for resource_name in dependency_graph.static_order():
        resource_name = cast(str, resource_name)
        endpoint_resource = endpoint_resource_map[resource_name]
        endpoint_config = cast(Endpoint, endpoint_resource.get("endpoint"))
        request_params = endpoint_config.get("params", {})
        request_json = endpoint_config.get("json", None)
        paginator = create_paginator(endpoint_config.get("paginator"))

        resolved_param: ResolvedParam | None = resolved_param_map[resource_name]

        include_from_parent: list[str] = endpoint_resource.get("include_from_parent", [])
        if not resolved_param and include_from_parent:
            raise ValueError(
                f"Resource {resource_name} has include_from_parent but is not " "dependent on another resource"
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

        if resolved_param is None:

            async def paginate_resource(
                method: HTTPMethodBasic,
                path: str,
                params: dict[str, Any],
                json: Optional[dict[str, Any]],
                paginator: Optional[BasePaginator],
                data_selector: Optional[jsonpath.TJsonPath],
                hooks: Optional[dict[str, Any]],
                client: RESTClient = client,
                incremental_object: Optional[Incremental[Any]] = incremental_object,
                incremental_param: Optional[IncrementalParam] = incremental_param,
                incremental_cursor_transform: Optional[Callable[..., Any]] = incremental_cursor_transform,
            ) -> AsyncGenerator[Iterator[Any], Any]:
                yield dlt.mark.materialize_table_schema()  # type: ignore

                if incremental_object:
                    params = _set_incremental_params(
                        params,
                        incremental_object,
                        incremental_param,
                        incremental_cursor_transform,
                    )

                yield client.paginate(
                    method=method,
                    path=path,
                    params=params,
                    json=json,
                    paginator=paginator,
                    data_selector=data_selector,
                    hooks=hooks,
                )

            resources[resource_name] = dlt.resource(
                paginate_resource,
                **resource_kwargs,  # TODO: implement typing.Unpack
            )(
                method=endpoint_config.get("method", "get"),
                path=endpoint_config.get("path"),
                params=request_params,
                json=request_json,
                paginator=paginator,
                data_selector=endpoint_config.get("data_selector"),
                hooks=hooks,
            )

        else:
            predecessor = resources[resolved_param.resolve_config["resource"]]

            base_params = exclude_keys(request_params, {resolved_param.param_name})

            async def paginate_dependent_resource(
                items: list[dict[str, Any]],
                method: HTTPMethodBasic,
                path: str,
                params: dict[str, Any],
                paginator: Optional[BasePaginator],
                data_selector: Optional[jsonpath.TJsonPath],
                hooks: Optional[dict[str, Any]],
                client: RESTClient = client,
                resolved_param: ResolvedParam = resolved_param,
                include_from_parent: list[str] = include_from_parent,
                incremental_object: Optional[Incremental[Any]] = incremental_object,
                incremental_param: Optional[IncrementalParam] = incremental_param,
                incremental_cursor_transform: Optional[Callable[..., Any]] = incremental_cursor_transform,
            ) -> AsyncGenerator[Any, Any]:
                yield dlt.mark.materialize_table_schema()  # type: ignore

                if incremental_object:
                    params = _set_incremental_params(
                        params,
                        incremental_object,
                        incremental_param,
                        incremental_cursor_transform,
                    )

                for item in items:
                    formatted_path, parent_record = process_parent_data_item(
                        path, item, resolved_param, include_from_parent
                    )

                    for child_page in client.paginate(
                        method=method,
                        path=formatted_path,
                        params=params,
                        paginator=paginator,
                        data_selector=data_selector,
                        hooks=hooks,
                    ):
                        if parent_record:
                            for child_record in child_page:
                                child_record.update(parent_record)
                        yield child_page

            resources[resource_name] = dlt.resource(  # type: ignore[call-overload]
                paginate_dependent_resource,
                data_from=predecessor,
                **resource_kwargs,  # TODO: implement typing.Unpack
            )(
                method=endpoint_config.get("method", "get"),
                path=endpoint_config.get("path"),
                params=base_params,
                paginator=paginator,
                data_selector=endpoint_config.get("data_selector"),
                hooks=hooks,
            )

    return resources


def _set_incremental_params(
    params: dict[str, Any],
    incremental_object: Incremental[Any],
    incremental_param: Optional[IncrementalParam],
    transform: Optional[Callable[..., Any]],
) -> dict[str, Any]:
    def identity_func(x: Any) -> Any:
        return x

    if transform is None:
        transform = identity_func

    if incremental_param is None:
        return params

    params[incremental_param.start] = transform(incremental_object.last_value)
    if incremental_param.end:
        params[incremental_param.end] = transform(incremental_object.end_value)
    return params
