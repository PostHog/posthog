from typing import Any, cast

from drf_spectacular.utils import extend_schema
from pydantic import BaseModel, Field
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import (
    AccountsTableQuery,
    AccountsTableQueryResponse,
    DashboardFilter,
    LimitContext,
    QueryStatusResponse,
    RefreshType,
)

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import PydanticModelMixin
from posthog.api.query import QueryViewSet
from posthog.api.query_coalescer import QueryCoalescingMixin
from posthog.api.routing import TeamAndOrgViewSetMixin


class AccountsTableQueryRequest(BaseModel):
    async_: bool | None = Field(default=None, alias="async")
    query: AccountsTableQuery = Field(description="Accounts table query to run.")
    client_query_id: str | None = Field(
        default=None,
        description="Client-provided query ID for checking status or canceling an asynchronous query.",
    )
    filters_override: DashboardFilter | None = None
    limit_context: LimitContext | None = Field(
        default=None,
        description="Limit context for the query. Only 'posthog_ai' is allowed as a client-provided value.",
    )
    name: str | None = Field(
        default=None,
        description="Name given to a query. It's used to identify the query in the UI. Up to 128 characters for a name.",
    )
    refresh: RefreshType = Field(
        default=RefreshType.BLOCKING,
        description="Cache and execution behavior for the query.",
    )
    variables_override: dict[str, dict[str, Any]] | None = None


class AccountsTableQueryViewSet(
    QueryCoalescingMixin,
    TeamAndOrgViewSetMixin,
    PydanticModelMixin,
    viewsets.ViewSet,
):
    scope_object = "account"
    scope_object_read_actions = ["create"]
    serializer_class = _FallbackSerializer

    get_throttles = QueryViewSet.get_throttles
    check_team_api_queries_concurrency = QueryViewSet.check_team_api_queries_concurrency
    _raise_concurrency_throttled = QueryViewSet._raise_concurrency_throttled
    handle_column_ch_error = QueryViewSet.handle_column_ch_error
    _tag_client_query_id = QueryViewSet._tag_client_query_id
    _try_format_for_llm = QueryViewSet._try_format_for_llm
    _validate_query_kind = QueryViewSet._validate_query_kind

    def dangerously_get_required_scopes(self, _request: Request, _view: Any) -> list[str] | None:
        if self.action == "create":
            return ["account:read"]
        return None

    @extend_schema(
        description="Run a Customer Analytics accounts table query.",
        operation_id="customer_analytics_accounts_table_query_create",
        request=AccountsTableQueryRequest,
        responses={200: AccountsTableQueryResponse, 202: QueryStatusResponse},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = request.data.get("query") if isinstance(request.data, dict) else None
        if not isinstance(query, dict) or query.get("kind") != "AccountsTableQuery":
            raise ValidationError("Only AccountsTableQuery is supported.")
        return QueryViewSet.create(cast(QueryViewSet, self), request, *args, **kwargs)
