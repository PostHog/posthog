from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, TypedDict

from dlt.common import jsonpath
from dlt.common.schema.typing import (
    TAnySchemaColumns,
    TColumnNames,
    TSchemaContract,
    TTableFormat,
    TWriteDispositionConfig,
)
from dlt.common.typing import TSortOrder
from dlt.extract.incremental.typing import LastValueFunc
from dlt.extract.items import TTableHintTemplate
from dlt.sources.helpers.rest_client.auth import (
    APIKeyAuth,
    AuthConfigBase,
    BearerTokenAuth,
    HttpBasicAuth,
    TApiKeyLocation,
)
from dlt.sources.helpers.rest_client.paginators import (
    BasePaginator,
    HeaderLinkPaginator,
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    OffsetPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from dlt.sources.helpers.rest_client.typing import HTTPMethodBasic

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
    """A paginator that uses page number-based pagination strategy."""

    initial_page: int | None
    page_param: str | None
    total_path: jsonpath.TJsonPath | None
    maximum_page: int | None


class OffsetPaginatorConfig(PaginatorTypeConfig, total=False):
    """A paginator that uses offset-based pagination strategy."""

    limit: int
    offset: int | None
    offset_param: str | None
    limit_param: str | None
    total_path: jsonpath.TJsonPath | None
    maximum_offset: int | None


class HeaderLinkPaginatorConfig(PaginatorTypeConfig, total=False):
    """A paginator that uses the 'Link' header in HTTP responses
    for pagination."""

    links_next_key: str | None


class JSONResponsePaginatorConfig(PaginatorTypeConfig, total=False):
    """Locates the next page URL within the JSON response body. The key
    containing the URL can be specified using a JSON path."""

    next_url_path: jsonpath.TJsonPath | None


class JSONResponseCursorPaginatorConfig(PaginatorTypeConfig, total=False):
    """Uses a cursor parameter for pagination, with the cursor value found in
    the JSON response body."""

    cursor_path: jsonpath.TJsonPath | None
    cursor_param: str | None


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
    """Uses `token` for Bearer authentication in "Authorization" header."""

    # we allow for a shorthand form of bearer auth, without a type
    type: Optional[AuthType]  # noqa
    token: str


class ApiKeyAuthConfig(AuthTypeConfig, total=False):
    """Uses provided `api_key` to create authorization data in the specified `location` (query, param, header, cookie) under specified `name`"""

    name: str | None
    api_key: str
    location: TApiKeyLocation | None


class HttpBasicAuthConfig(AuthTypeConfig, total=True):
    """Uses HTTP basic authentication"""

    username: str
    password: str


# TODO: add later
# class OAuthJWTAuthConfig(AuthTypeConfig, total=True):


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
    headers: dict[str, str] | None
    auth: AuthConfig | None
    paginator: PaginatorConfig | None


class IncrementalArgs(TypedDict, total=False):
    cursor_path: str
    initial_value: str | None
    last_value_func: LastValueFunc[str] | None
    primary_key: TTableHintTemplate[TColumnNames] | None
    end_value: str | None
    row_order: TSortOrder | None
    convert: Callable[..., Any] | None


class IncrementalConfig(IncrementalArgs, total=False):
    start_param: str
    end_param: str | None


ParamBindType = Literal["resolve", "incremental"]


class ParamBindConfig(TypedDict):
    type: ParamBindType  # noqa


class ResolveParamConfig(ParamBindConfig):
    resource: str
    field: str


class IncrementalParamConfig(ParamBindConfig, IncrementalArgs):
    pass
    # TODO: implement param type to bind incremental to
    # param_type: Optional[Literal["start_param", "end_param"]]


@dataclass
class ResolvedParam:
    param_name: str
    resolve_config: ResolveParamConfig
    field_path: jsonpath.TJsonPath = field(init=False)

    def __post_init__(self) -> None:
        self.field_path = jsonpath.compile_path(self.resolve_config["field"])


class ResponseAction(TypedDict, total=False):
    status_code: int | str | None
    content: str | None
    action: str


class Endpoint(TypedDict, total=False):
    path: str | None
    method: HTTPMethodBasic | None
    params: dict[str, ResolveParamConfig | IncrementalParamConfig | Any] | None
    json: dict[str, Any] | None
    paginator: PaginatorConfig | None
    data_selector: jsonpath.TJsonPath | None
    response_actions: list[ResponseAction] | None
    incremental: IncrementalConfig | None


class ResourceBase(TypedDict, total=False):
    """Defines hints that may be passed to `dlt.resource` decorator"""

    table_name: TTableHintTemplate[str] | None
    max_table_nesting: int | None
    write_disposition: TTableHintTemplate[TWriteDispositionConfig] | None
    parent: TTableHintTemplate[str] | None
    columns: TTableHintTemplate[TAnySchemaColumns] | None
    primary_key: TTableHintTemplate[TColumnNames] | None
    merge_key: TTableHintTemplate[TColumnNames] | None
    schema_contract: TTableHintTemplate[TSchemaContract] | None
    table_format: TTableHintTemplate[TTableFormat] | None
    selected: bool | None
    parallelized: bool | None


class EndpointResourceBase(ResourceBase, total=False):
    endpoint: str | Endpoint | None
    include_from_parent: list[str] | None


class EndpointResource(EndpointResourceBase, total=False):
    name: TTableHintTemplate[str]


class RESTAPIConfig(TypedDict):
    client: ClientConfig
    resource_defaults: EndpointResourceBase | None
    resources: list[str | EndpointResource]
