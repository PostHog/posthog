import string
import graphlib  # type: ignore[import,unused-ignore]
import warnings
from collections.abc import Callable
from copy import copy
from typing import Any, NamedTuple, Optional, Union

import dlt
from dlt.common import jsonpath, logger
from dlt.common.configuration import resolve_configuration
from dlt.common.schema.utils import merge_columns
from dlt.common.utils import update_dict_nested
from dlt.extract.incremental import Incremental
from dlt.extract.utils import ensure_table_schema_columns
from dlt.sources.helpers.requests import Response
from dlt.sources.helpers.rest_client.auth import APIKeyAuth, AuthConfigBase, BearerTokenAuth, HttpBasicAuth
from dlt.sources.helpers.rest_client.detector import single_entity_path
from dlt.sources.helpers.rest_client.exceptions import IgnoreResponseException
from dlt.sources.helpers.rest_client.paginators import (
    BasePaginator,
    HeaderLinkPaginator,
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    OffsetPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)

from .typing import (
    AuthConfig,
    AuthType,
    Endpoint,
    EndpointResource,
    EndpointResourceBase,
    IncrementalConfig,
    PaginatorConfig,
    PaginatorType,
    ResolvedParam,
    ResponseAction,
)
from .utils import exclude_keys

PAGINATOR_MAP: dict[PaginatorType, type[BasePaginator]] = {
    "json_response": JSONResponsePaginator,
    "header_link": HeaderLinkPaginator,
    "auto": None,
    "single_page": SinglePagePaginator,
    "cursor": JSONResponseCursorPaginator,
    "offset": OffsetPaginator,
    "page_number": PageNumberPaginator,
}

AUTH_MAP: dict[AuthType, type[AuthConfigBase]] = {
    "bearer": BearerTokenAuth,
    "api_key": APIKeyAuth,
    "http_basic": HttpBasicAuth,
}


class IncrementalParam(NamedTuple):
    start: str
    end: Optional[str]


def get_paginator_class(paginator_type: PaginatorType) -> type[BasePaginator]:
    try:
        return PAGINATOR_MAP[paginator_type]
    except KeyError:
        available_options = ", ".join(PAGINATOR_MAP.keys())
        raise ValueError(f"Invalid paginator: {paginator_type}. " f"Available options: {available_options}")


def create_paginator(
    paginator_config: Optional[PaginatorConfig],
) -> Optional[BasePaginator]:
    if isinstance(paginator_config, BasePaginator):
        return paginator_config

    if isinstance(paginator_config, str):
        paginator_class = get_paginator_class(paginator_config)
        try:
            # `auto` has no associated class in `PAGINATOR_MAP`
            return paginator_class() if paginator_class else None
        except TypeError:
            raise ValueError(
                f"Paginator {paginator_config} requires arguments to create an instance. Use {paginator_class} instance instead."
            )

    if isinstance(paginator_config, dict):
        paginator_type = paginator_config.get("type", "auto")
        paginator_class = get_paginator_class(paginator_type)
        return paginator_class(**exclude_keys(paginator_config, {"type"})) if paginator_class else None

    return None


def get_auth_class(auth_type: AuthType) -> type[AuthConfigBase]:
    try:
        return AUTH_MAP[auth_type]
    except KeyError:
        available_options = ", ".join(AUTH_MAP.keys())
        raise ValueError(f"Invalid paginator: {auth_type}. " f"Available options: {available_options}")


def create_auth(auth_config: Optional[AuthConfig]) -> Optional[AuthConfigBase]:
    auth: AuthConfigBase = None
    if isinstance(auth_config, AuthConfigBase):
        auth = auth_config

    if isinstance(auth_config, str):
        auth_class = get_auth_class(auth_config)
        auth = auth_class()

    if isinstance(auth_config, dict):
        auth_type = auth_config.get("type", "bearer")
        auth_class = get_auth_class(auth_type)
        auth = auth_class(**exclude_keys(auth_config, {"type"}))

    if auth:
        # TODO: provide explicitly (non-default) values as explicit explicit_value=dict(auth)
        # this will resolve auth which is a configuration using current section context
        return resolve_configuration(auth)

    return None


def setup_incremental_object(
    request_params: dict[str, Any],
    incremental_config: Optional[IncrementalConfig] = None,
) -> tuple[Optional[Incremental[Any]], Optional[IncrementalParam], Optional[Callable[..., Any]]]:
    incremental_params: list[str] = []
    for param_name, param_config in request_params.items():
        if (
            isinstance(param_config, dict)
            and param_config.get("type") == "incremental"
            or isinstance(param_config, dlt.sources.incremental)
        ):
            incremental_params.append(param_name)
    if len(incremental_params) > 1:
        raise ValueError(f"Only a single incremental parameter is allower per endpoint. Found: {incremental_params}")
    convert: Optional[Callable[..., Any]]
    for param_name, param_config in request_params.items():
        if isinstance(param_config, dlt.sources.incremental):
            if param_config.end_value is not None:
                raise ValueError(
                    f"Only initial_value is allowed in the configuration of param: {param_name}. To set end_value too use the incremental configuration at the resource level. See https://dlthub.com/docs/dlt-ecosystem/verified-sources/rest_api#incremental-loading/"
                )
            return param_config, IncrementalParam(start=param_name, end=None), None
        if isinstance(param_config, dict) and param_config.get("type") == "incremental":
            if param_config.get("end_value") or param_config.get("end_param"):
                raise ValueError(
                    f"Only start_param and initial_value are allowed in the configuration of param: {param_name}. To set end_value too use the incremental configuration at the resource level. See https://dlthub.com/docs/dlt-ecosystem/verified-sources/rest_api#incremental-loading"
                )
            convert = parse_convert_or_deprecated_transform(param_config)

            config = exclude_keys(param_config, {"type", "convert", "transform"})
            # TODO: implement param type to bind incremental to
            return (
                dlt.sources.incremental(**config),
                IncrementalParam(start=param_name, end=None),
                convert,
            )
    if incremental_config:
        convert = parse_convert_or_deprecated_transform(incremental_config)
        config = exclude_keys(incremental_config, {"start_param", "end_param", "convert", "transform"})
        return (
            dlt.sources.incremental(**config),
            IncrementalParam(
                start=incremental_config["start_param"],
                end=incremental_config.get("end_param"),
            ),
            convert,
        )

    return None, None, None


def parse_convert_or_deprecated_transform(
    config: Union[IncrementalConfig, dict[str, Any]],
) -> Optional[Callable[..., Any]]:
    convert = config.get("convert", None)
    deprecated_transform = config.get("transform", None)
    if deprecated_transform:
        warnings.warn(
            "The key `transform` is deprecated in the incremental configuration and it will be removed. "
            "Use `convert` instead",
            DeprecationWarning,
            stacklevel=2,
        )
        convert = deprecated_transform
    return convert


def make_parent_key_name(resource_name: str, field_name: str) -> str:
    return f"_{resource_name}_{field_name}"


def build_resource_dependency_graph(
    resource_defaults: EndpointResourceBase,
    resource_list: list[str | EndpointResource],
) -> tuple[Any, dict[str, EndpointResource], dict[str, Optional[ResolvedParam]]]:
    dependency_graph = graphlib.TopologicalSorter()
    endpoint_resource_map: dict[str, EndpointResource] = {}
    resolved_param_map: dict[str, ResolvedParam] = {}

    # expand all resources and index them
    for resource_kwargs in resource_list:
        if isinstance(resource_kwargs, dict):
            # clone resource here, otherwise it needs to be cloned in several other places
            # note that this clones only dict structure, keeping all instances without deepcopy
            resource_kwargs = update_dict_nested({}, resource_kwargs)  # type: ignore

        endpoint_resource = _make_endpoint_resource(resource_kwargs, resource_defaults)
        assert isinstance(endpoint_resource["endpoint"], dict)
        _setup_single_entity_endpoint(endpoint_resource["endpoint"])
        _bind_path_params(endpoint_resource)

        resource_name = endpoint_resource["name"]
        assert isinstance(resource_name, str), f"Resource name must be a string, got {type(resource_name)}"

        if resource_name in endpoint_resource_map:
            raise ValueError(f"Resource {resource_name} has already been defined")
        endpoint_resource_map[resource_name] = endpoint_resource

    # create dependency graph
    for resource_name, endpoint_resource in endpoint_resource_map.items():
        assert isinstance(endpoint_resource["endpoint"], dict)
        # connect transformers to resources via resolved params
        resolved_params = _find_resolved_params(endpoint_resource["endpoint"])
        if len(resolved_params) > 1:
            raise ValueError(f"Multiple resolved params for resource {resource_name}: {resolved_params}")
        elif len(resolved_params) == 1:
            resolved_param = resolved_params[0]
            predecessor = resolved_param.resolve_config["resource"]
            if predecessor not in endpoint_resource_map:
                raise ValueError(
                    f"A transformer resource {resource_name} refers to non existing parent resource {predecessor} on {resolved_param}"
                )
            dependency_graph.add(resource_name, predecessor)
            resolved_param_map[resource_name] = resolved_param
        else:
            dependency_graph.add(resource_name)
            resolved_param_map[resource_name] = None

    return dependency_graph, endpoint_resource_map, resolved_param_map


def _make_endpoint_resource(resource: str | EndpointResource, default_config: EndpointResourceBase) -> EndpointResource:
    """
    Creates an EndpointResource object based on the provided resource
    definition and merges it with the default configuration.

    This function supports defining a resource in multiple formats:
    - As a string: The string is interpreted as both the resource name
        and its endpoint path.
    - As a dictionary: The dictionary must include `name` and `endpoint`
        keys. The `endpoint` can be a string representing the path,
        or a dictionary for more complex configurations. If the `endpoint`
        is missing the `path` key, the resource name is used as the `path`.
    """
    if isinstance(resource, str):
        resource = {"name": resource, "endpoint": {"path": resource}}
        return _merge_resource_endpoints(default_config, resource)

    if "endpoint" in resource:
        if isinstance(resource["endpoint"], str):
            resource["endpoint"] = {"path": resource["endpoint"]}
    else:
        # endpoint is optional
        resource["endpoint"] = {}

    if "path" not in resource["endpoint"]:
        resource["endpoint"]["path"] = resource["name"]  # type: ignore

    return _merge_resource_endpoints(default_config, resource)


def _bind_path_params(resource: EndpointResource) -> None:
    """Binds params declared in path to params available in `params`. Pops the
    bound params but. Params of type `resolve` and `incremental` are skipped
    and bound later.
    """
    path_params: dict[str, Any] = {}
    assert isinstance(resource["endpoint"], dict)  # type guard
    resolve_params = [r.param_name for r in _find_resolved_params(resource["endpoint"])]
    path = resource["endpoint"]["path"]
    for format_ in string.Formatter().parse(path):
        name = format_[1]
        if name:
            params = resource["endpoint"].get("params", {})
            if name not in params and name not in path_params:
                raise ValueError(
                    f"The path {path} defined in resource {resource['name']} requires param with name {name} but it is not found in {params}"
                )
            if name in resolve_params:
                resolve_params.remove(name)
            if name in params:
                if not isinstance(params[name], dict):
                    # bind resolved param and pop it from endpoint
                    path_params[name] = params.pop(name)
                else:
                    param_type = params[name].get("type")
                    if param_type != "resolve":
                        raise ValueError(
                            f"The path {path} defined in resource {resource['name']} tries to bind param {name} with type {param_type}. Paths can only bind 'resource' type params."
                        )
                    # resolved params are bound later
                    path_params[name] = "{" + name + "}"

    if len(resolve_params) > 0:
        raise NotImplementedError(
            f"Resource {resource['name']} defines resolve params {resolve_params} that are not bound in path {path}. Resolve query params not supported yet."
        )

    resource["endpoint"]["path"] = path.format(**path_params)


def _setup_single_entity_endpoint(endpoint: Endpoint) -> Endpoint:
    """Tries to guess if the endpoint refers to a single entity and when detected:
    * if `data_selector` was not specified (or is None), "$" is selected
    * if `paginator` was not specified (or is None), SinglePagePaginator is selected

    Endpoint is modified in place and returned
    """
    # try to guess if list of entities or just single entity is returned
    if single_entity_path(endpoint["path"]):
        if endpoint.get("data_selector") is None:
            endpoint["data_selector"] = "$"
        if endpoint.get("paginator") is None:
            endpoint["paginator"] = SinglePagePaginator()
    return endpoint


def _find_resolved_params(endpoint_config: Endpoint) -> list[ResolvedParam]:
    """
    Find all resolved params in the endpoint configuration and return
    a list of ResolvedParam objects.

    Resolved params are of type ResolveParamConfig (bound param with a key "type" set to "resolve".)
    """
    return [
        ResolvedParam(key, value)  # type: ignore[arg-type]
        for key, value in endpoint_config.get("params", {}).items()
        if (isinstance(value, dict) and value.get("type") == "resolve")
    ]


def _handle_response_actions(response: Response, actions: list[ResponseAction]) -> Optional[str]:
    """Handle response actions based on the response and the provided actions."""
    content = response.text

    for action in actions:
        status_code = action.get("status_code")
        content_substr: str = action.get("content")
        action_type: str = action.get("action")

        if status_code is not None and content_substr is not None:
            if response.status_code == status_code and content_substr in content:
                return action_type

        elif status_code is not None:
            if response.status_code == status_code:
                return action_type

        elif content_substr is not None:
            if content_substr in content:
                return action_type

    return None


def _create_response_actions_hook(
    response_actions: list[ResponseAction],
) -> Callable[[Response, Any, Any], None]:
    def response_actions_hook(response: Response, *args: Any, **kwargs: Any) -> None:
        action_type = _handle_response_actions(response, response_actions)
        if action_type == "ignore":
            logger.info(f"Ignoring response with code {response.status_code} " f"and content '{response.json()}'.")
            raise IgnoreResponseException

        # If no action has been taken and the status code indicates an error,
        # raise an HTTP error based on the response status
        if not action_type and response.status_code >= 400:
            response.raise_for_status()

    return response_actions_hook


def create_response_hooks(
    response_actions: Optional[list[ResponseAction]],
) -> Optional[dict[str, Any]]:
    """Create response hooks based on the provided response actions. Note
    that if the error status code is not handled by the response actions,
    the default behavior is to raise an HTTP error.

    Example:
        response_actions = [
            {"status_code": 404, "action": "ignore"},
            {"content": "Not found", "action": "ignore"},
            {"status_code": 429, "action": "retry"},
            {"status_code": 200, "content": "some text", "action": "retry"},
        ]
        hooks = create_response_hooks(response_actions)
    """
    if response_actions:
        return {"response": [_create_response_actions_hook(response_actions)]}
    return None


def process_parent_data_item(
    path: str,
    item: dict[str, Any],
    resolved_param: ResolvedParam,
    include_from_parent: list[str],
) -> tuple[str, dict[str, Any]]:
    parent_resource_name = resolved_param.resolve_config["resource"]

    field_values = jsonpath.find_values(resolved_param.field_path, item)

    if not field_values:
        field_path = resolved_param.resolve_config["field"]
        raise ValueError(
            f"Transformer expects a field '{field_path}' to be present in the incoming data from resource {parent_resource_name} in order to bind it to path param {resolved_param.param_name}. Available parent fields are {', '.join(item.keys())}"
        )
    bound_path = path.format(**{resolved_param.param_name: field_values[0]})

    parent_record: dict[str, Any] = {}
    if include_from_parent:
        for parent_key in include_from_parent:
            child_key = make_parent_key_name(parent_resource_name, parent_key)
            if parent_key not in item:
                raise ValueError(
                    f"Transformer expects a field '{parent_key}' to be present in the incoming data from resource {parent_resource_name} in order to include it in child records under {child_key}. Available parent fields are {', '.join(item.keys())}"
                )
            parent_record[child_key] = item[parent_key]

    return bound_path, parent_record


def _merge_resource_endpoints(default_config: EndpointResourceBase, config: EndpointResource) -> EndpointResource:
    """Merges `default_config` and `config`, returns new instance of EndpointResource"""
    # NOTE: config is normalized and always has "endpoint" field which is a dict
    # TODO: could deep merge paginators and auths of the same type

    default_endpoint = default_config.get("endpoint", Endpoint())
    assert isinstance(default_endpoint, dict)
    config_endpoint = config["endpoint"]
    assert isinstance(config_endpoint, dict)

    merged_endpoint: Endpoint = {
        **default_endpoint,
        **{k: v for k, v in config_endpoint.items() if k not in ("json", "params")},  # type: ignore[typeddict-item]
    }
    # merge endpoint, only params and json are allowed to deep merge
    if "json" in config_endpoint:
        merged_endpoint["json"] = {
            **(merged_endpoint.get("json", {})),
            **config_endpoint["json"],
        }
    if "params" in config_endpoint:
        merged_endpoint["params"] = {
            **(merged_endpoint.get("json", {})),
            **config_endpoint["params"],
        }
    # merge columns
    if (default_columns := default_config.get("columns")) and (columns := config.get("columns")):
        # merge only native dlt formats, skip pydantic and others
        if isinstance(columns, list | dict) and isinstance(default_columns, list | dict):
            # normalize columns
            columns = ensure_table_schema_columns(columns)
            default_columns = ensure_table_schema_columns(default_columns)
            # merge columns with deep merging hints
            config["columns"] = merge_columns(copy(default_columns), columns, merge_columns=True)

    # no need to deep merge resources
    merged_resource: EndpointResource = {
        **default_config,
        **config,
        "endpoint": merged_endpoint,
    }
    return merged_resource
