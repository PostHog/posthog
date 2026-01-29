"""
Type definitions for REST API sources.

Replaces DLT type imports with simplified versions that maintain compatibility.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, TypedDict, TypeVar, Union

from .auth import APIKeyAuth, AuthBase, BearerTokenAuth, HttpBasicAuth
from .pagination import (
    BasePaginator,
    HeaderLinkPaginator,
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    OffsetPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)

# Type aliases for simplified schema handling
TJsonPath = str
TAnySchemaColumns = Any  # dict or list of column definitions
TColumnNames = Union[str, list[str]]
TSchemaContract = dict[str, Any]
TTableFormat = str
TWriteDispositionConfig = Union[str, dict[str, str]]

# Generic type for table hints - can be a value, callable, or None
_T = TypeVar("_T")
TTableHintTemplate = Union[_T, Callable[..., _T], None]

TSortOrder = Literal["asc", "desc"]
TApiKeyLocation = Literal["header", "query", "cookie", "param"]
HTTPMethodBasic = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]

# Pagination types
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
    type: PaginatorType


class PageNumberPaginatorConfig(PaginatorTypeConfig, total=False):
    """A paginator that uses page number-based pagination strategy."""

    initial_page: Optional[int]
    page_param: Optional[str]
    total_path: Optional[TJsonPath]
    maximum_page: Optional[int]


class OffsetPaginatorConfig(PaginatorTypeConfig, total=False):
    """A paginator that uses offset-based pagination strategy."""

    limit: int
    offset: Optional[int]
    offset_param: Optional[str]
    limit_param: Optional[str]
    total_path: Optional[TJsonPath]
    maximum_offset: Optional[int]


class HeaderLinkPaginatorConfig(PaginatorTypeConfig, total=False):
    """A paginator that uses the 'Link' header in HTTP responses for pagination."""

    links_next_key: Optional[str]


class JSONResponsePaginatorConfig(PaginatorTypeConfig, total=False):
    """Locates the next page URL within the JSON response body."""

    next_url_path: Optional[TJsonPath]


class JSONResponseCursorPaginatorConfig(PaginatorTypeConfig, total=False):
    """Uses a cursor parameter for pagination, with the cursor value found in the JSON response body."""

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

# Authentication types
AuthType = Literal["bearer", "api_key", "http_basic"]


class AuthTypeConfig(TypedDict, total=True):
    type: AuthType


class BearerTokenAuthConfig(TypedDict, total=False):
    """Uses `token` for Bearer authentication in "Authorization" header."""

    type: Optional[AuthType]
    token: str


class ApiKeyAuthConfig(AuthTypeConfig, total=False):
    """Uses provided `api_key` to create authorization data in the specified `location`."""

    name: Optional[str]
    api_key: str
    location: Optional[TApiKeyLocation]


class HttpBasicAuthConfig(AuthTypeConfig, total=True):
    """Uses HTTP basic authentication."""

    username: str
    password: str


AuthConfig = (
    AuthBase
    | AuthType
    | BearerTokenAuthConfig
    | ApiKeyAuthConfig
    | HttpBasicAuthConfig
    | BearerTokenAuth
    | APIKeyAuth
    | HttpBasicAuth
)


class ClientConfig(TypedDict, total=False):
    """Configuration for the REST API client."""

    base_url: str
    headers: Optional[dict[str, str]]
    auth: Optional[AuthConfig]
    paginator: Optional[PaginatorConfig]


class IncrementalArgs(TypedDict, total=False):
    """Arguments for incremental loading configuration."""

    cursor_path: str
    initial_value: Optional[str]
    primary_key: Optional[TTableHintTemplate[TColumnNames]]
    end_value: Optional[str]
    row_order: Optional[TSortOrder]
    convert: Optional[Callable[..., Any]]


class IncrementalConfig(IncrementalArgs, total=False):
    """Configuration for incremental loading with parameters."""

    start_param: str
    end_param: Optional[str]


ParamBindType = Literal["resolve", "incremental"]


class ParamBindConfig(TypedDict):
    type: ParamBindType


class ResolveParamConfig(ParamBindConfig):
    """Configuration for resolved parameters (not implemented - removed unused feature)."""

    resource: str
    field: str


class IncrementalParamConfig(ParamBindConfig, IncrementalArgs):
    """Configuration for incremental parameters."""

    pass


@dataclass
class ResolvedParam:
    """Resolved parameter for resource dependencies (not used - removed feature)."""

    param_name: str
    resolve_config: ResolveParamConfig
    field_path: TJsonPath = field(init=False)

    def __post_init__(self) -> None:
        from .jsonpath_utils import compile_path

        self.field_path = compile_path(self.resolve_config["field"])


class ResponseAction(TypedDict, total=False):
    """Configuration for response-based actions."""

    status_code: Optional[int | str]
    content: Optional[str]
    action: str


class Endpoint(TypedDict, total=False):
    """Configuration for a REST API endpoint."""

    path: Optional[str]
    method: Optional[HTTPMethodBasic]
    params: Optional[dict[str, ResolveParamConfig | IncrementalParamConfig | Any]]
    json: Optional[dict[str, Any]]
    paginator: Optional[PaginatorConfig]
    data_selector: Optional[TJsonPath]
    response_actions: Optional[list[ResponseAction]]
    incremental: Optional[IncrementalConfig]


class ResourceBase(TypedDict, total=False):
    """Base resource hints."""

    table_name: Optional[TTableHintTemplate[str]]
    max_table_nesting: Optional[int]
    write_disposition: Optional[TTableHintTemplate[TWriteDispositionConfig]]
    parent: Optional[TTableHintTemplate[str]]
    columns: Optional[TTableHintTemplate[TAnySchemaColumns]]
    primary_key: Optional[TTableHintTemplate[TColumnNames]]
    merge_key: Optional[TTableHintTemplate[TColumnNames]]
    schema_contract: Optional[TTableHintTemplate[TSchemaContract]]
    table_format: Optional[TTableHintTemplate[TTableFormat]]
    selected: Optional[bool]
    parallelized: Optional[bool]


class EndpointResourceBase(ResourceBase, total=False):
    """Base resource configuration with endpoint."""

    endpoint: Optional[str | Endpoint]
    include_from_parent: Optional[list[str]]


class EndpointResource(EndpointResourceBase, total=False):
    """Complete resource configuration."""

    name: TTableHintTemplate[str]


class RESTAPIConfig(TypedDict):
    """Main configuration for REST API source."""

    client: ClientConfig
    resource_defaults: Optional[EndpointResourceBase]
    resources: list[str | EndpointResource]
