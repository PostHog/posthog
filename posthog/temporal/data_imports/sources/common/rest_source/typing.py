from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, TypedDict

from .auth import APIKeyAuth, AuthConfigBase, BearerTokenAuth, HttpBasicAuth, TApiKeyLocation
from .jsonpath_utils import TJsonPath, compile_path
from .paginators import (
    BasePaginator,
    HeaderLinkPaginator,
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    OffsetPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)

HTTPMethodBasic = Literal["get", "post", "put", "patch", "delete", "GET", "POST", "PUT", "PATCH", "DELETE"]
TSortOrder = Literal["asc", "desc"]
LastValueFunc = Callable[..., Any]
TTableHintTemplate = Any
TAnySchemaColumns = Any
TColumnNames = Any
TSchemaContract = Any
TTableFormat = Any
TWriteDispositionConfig = Any

PaginatorType = Literal[
    "json_response",
    "header_link",
    "auto",
    "single_page",
    "cursor",
    "offset",
    "page_number",
]


class PaginatorTypeConfig(TypedDict, total=True):
    type: PaginatorType  # noqa


class PageNumberPaginatorConfig(PaginatorTypeConfig, total=False):
    initial_page: Optional[int]
    page_param: Optional[str]
    total_path: Optional[TJsonPath]
    maximum_page: Optional[int]


class OffsetPaginatorConfig(PaginatorTypeConfig, total=False):
    limit: int
    offset: Optional[int]
    offset_param: Optional[str]
    limit_param: Optional[str]
    total_path: Optional[TJsonPath]
    maximum_offset: Optional[int]


class HeaderLinkPaginatorConfig(PaginatorTypeConfig, total=False):
    links_next_key: Optional[str]


class JSONResponsePaginatorConfig(PaginatorTypeConfig, total=False):
    next_url_path: Optional[TJsonPath]


class JSONResponseCursorPaginatorConfig(PaginatorTypeConfig, total=False):
    cursor_path: Optional[TJsonPath]
    cursor_param: Optional[str]


PaginatorConfig = (
    PaginatorType
    | PageNumberPaginatorConfig
    | OffsetPaginatorConfig
    | HeaderLinkPaginatorConfig
    | JSONResponsePaginatorConfig
    | JSONResponseCursorPaginatorConfig
    | BasePaginator
    | SinglePagePaginator
    | HeaderLinkPaginator
    | JSONResponsePaginator
    | JSONResponseCursorPaginator
    | OffsetPaginator
    | PageNumberPaginator
)


AuthType = Literal["bearer", "api_key", "http_basic"]


class AuthTypeConfig(TypedDict, total=True):
    type: AuthType  # noqa


class BearerTokenAuthConfig(TypedDict, total=False):
    type: Optional[AuthType]  # noqa
    token: str


class ApiKeyAuthConfig(AuthTypeConfig, total=False):
    name: Optional[str]
    api_key: str
    location: Optional[TApiKeyLocation]


class HttpBasicAuthConfig(AuthTypeConfig, total=True):
    username: str
    password: str


AuthConfig = (
    AuthConfigBase
    | AuthType
    | BearerTokenAuthConfig
    | ApiKeyAuthConfig
    | HttpBasicAuthConfig
    | BearerTokenAuth
    | APIKeyAuth
    | HttpBasicAuth
)


class ClientConfig(TypedDict, total=False):
    base_url: str
    headers: Optional[dict[str, str]]
    auth: Optional[AuthConfig]
    paginator: Optional[PaginatorConfig]


class IncrementalArgs(TypedDict, total=False):
    cursor_path: str
    initial_value: Optional[str]
    last_value_func: Optional[LastValueFunc]
    end_value: Optional[str]
    row_order: Optional[TSortOrder]
    convert: Optional[Callable[..., Any]]


class IncrementalConfig(IncrementalArgs, total=False):
    start_param: str
    end_param: Optional[str]


ParamBindType = Literal["resolve", "incremental"]


class ParamBindConfig(TypedDict):
    type: ParamBindType  # noqa


class ResolveParamConfig(ParamBindConfig):
    resource: str
    field: str


class IncrementalParamConfig(ParamBindConfig, IncrementalArgs):
    pass


@dataclass
class ResolvedParam:
    param_name: str
    resolve_config: ResolveParamConfig
    field_path: TJsonPath = field(init=False)

    def __post_init__(self) -> None:
        self.field_path = compile_path(self.resolve_config["field"])


class ResponseAction(TypedDict, total=False):
    status_code: Optional[int | str]
    content: Optional[str]
    action: str


class Endpoint(TypedDict, total=False):
    path: Optional[str]
    method: Optional[HTTPMethodBasic]
    params: Optional[dict[str, ResolveParamConfig | IncrementalParamConfig | Any]]
    json: Optional[dict[str, Any]]
    paginator: Optional[PaginatorConfig]
    data_selector: Optional[TJsonPath]
    response_actions: Optional[list[ResponseAction]]
    incremental: Optional[IncrementalConfig]


class ResourceBase(TypedDict, total=False):
    table_name: Optional[TTableHintTemplate]
    max_table_nesting: Optional[int]
    write_disposition: Optional[TTableHintTemplate]
    parent: Optional[TTableHintTemplate]
    columns: Optional[TTableHintTemplate]
    primary_key: Optional[TTableHintTemplate]
    merge_key: Optional[TTableHintTemplate]
    schema_contract: Optional[TTableHintTemplate]
    table_format: Optional[TTableHintTemplate]
    selected: Optional[bool]
    parallelized: Optional[bool]


class EndpointResourceBase(ResourceBase, total=False):
    endpoint: Optional[str | Endpoint]
    include_from_parent: Optional[list[str]]


class EndpointResource(EndpointResourceBase, total=False):
    name: TTableHintTemplate


class RESTAPIConfig(TypedDict):
    client: ClientConfig
    resource_defaults: Optional[EndpointResourceBase]
    resources: list[str | EndpointResource]
