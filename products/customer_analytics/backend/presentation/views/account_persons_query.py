from typing import Any, Literal, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from pydantic import Field
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.schema import AccountUsersQuery, ActorsQuery, ActorsQueryResponse, QueryRequest, RefreshType

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.mixins import PydanticModelMixin
from posthog.api.query import QueryViewSet, add_query_response_identity_headers
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api_queries_budget import reset_request_query_cost
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import get_query_tag_value, tags_context
from posthog.errors import ExposedCHQueryError
from posthog.models import User

from products.customer_analytics.backend.facade.persons import (
    AccountPersonsOptions,
    AccountPersonsPropertyAccessError,
    list_account_person_memberships,
    list_account_persons,
)
from products.customer_analytics.backend.presentation.views.account_persons import (
    AccountPersonMembershipsRequestSerializer,
    AccountPersonMembershipsSerializer,
    AccountPersonsPageSerializer,
    AccountPersonsQuerySerializer,
    AccountPersonsWebBurstThrottle,
    AccountPersonsWebSustainedThrottle,
)


class AccountPersonsActorsQuery(ActorsQuery):
    source: AccountUsersQuery = Field(description="Account membership source for the table.")


class AccountPersonsQueryRequest(QueryRequest):
    query: AccountPersonsActorsQuery = Field(description="Account-user table query to run.")
    async_: Literal[False] | None = Field(default=None, alias="async")
    refresh: Literal[RefreshType.BLOCKING, RefreshType.FORCE_BLOCKING] | None = Field(
        default=RefreshType.BLOCKING,
        description="Read cached results or calculate synchronously.",
    )


class AccountPersonsViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "account"
    scope_object_read_actions = ["list", "create", "memberships"]
    serializer_class = AccountPersonsPageSerializer
    pagination_class = None

    check_team_api_queries_concurrency = QueryViewSet.check_team_api_queries_concurrency
    _raise_concurrency_throttled = QueryViewSet._raise_concurrency_throttled
    handle_column_ch_error = QueryViewSet.handle_column_ch_error
    _tag_client_query_id = QueryViewSet._tag_client_query_id
    _try_format_for_llm = QueryViewSet._try_format_for_llm
    _validate_query_kind = QueryViewSet._validate_query_kind

    def finalize_response(self, request: Request, response: Response, *args: Any, **kwargs: Any) -> Response:
        return add_query_response_identity_headers(super().finalize_response(request, response, *args, **kwargs))

    def get_throttles(self) -> list[BaseThrottle]:
        return [
            AccountPersonsWebBurstThrottle(),
            AccountPersonsWebSustainedThrottle(),
            *QueryViewSet.get_throttles(cast(QueryViewSet, self)),
        ]

    def dangerously_get_required_scopes(self, _request: Request, _view: object) -> list[str]:
        if self.action in {"create", "memberships"}:
            return ["query:read", "account:read", "person:read"]
        return ["account:read", "person:read"]

    @extend_schema(
        operation_id="accounts_persons_memberships_create",
        parameters=[OpenApiParameter("id", OpenApiTypes.UUID, OpenApiParameter.PATH)],
        request=AccountPersonMembershipsRequestSerializer,
        responses={200: AccountPersonMembershipsSerializer(many=True)},
    )
    @action(detail=False, methods=["POST"])
    def memberships(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = AccountPersonMembershipsRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            reset_request_query_cost()
            with tags_context(api_queries_budgeted=get_query_tag_value("access_method") == "personal_api_key"):
                memberships = list_account_person_memberships(
                    team=self.team,
                    user=cast(User, request.user),
                    account_id=self.kwargs["id"],
                    user_access_control=self.user_access_control,
                    person_ids=list(dict.fromkeys(str(value) for value in data.validated_data["person_ids"])),
                )
        except (ExposedHogQLError, ExposedCHQueryError) as error:
            raise ValidationError(str(error), getattr(error, "code_name", None)) from error
        except ConcurrencyLimitExceeded as error:
            QueryViewSet._raise_concurrency_throttled(cast(QueryViewSet, self), error)
        if memberships is None:
            return Response({"detail": "Not found."}, status=404)
        return Response(AccountPersonMembershipsSerializer(memberships, many=True).data)

    @extend_schema(
        operation_id="accounts_persons_retrieve",
        parameters=[OpenApiParameter("id", OpenApiTypes.UUID, OpenApiParameter.PATH), AccountPersonsQuerySerializer],
        responses={200: AccountPersonsPageSerializer(many=False)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = AccountPersonsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            reset_request_query_cost()
            with tags_context(api_queries_budgeted=get_query_tag_value("access_method") == "personal_api_key"):
                page = list_account_persons(
                    team=self.team,
                    user=cast(User, request.user),
                    account_id=self.kwargs["id"],
                    user_access_control=self.user_access_control,
                    options=AccountPersonsOptions(**query.validated_data),
                )
        except (ExposedHogQLError, ExposedCHQueryError) as error:
            raise ValidationError(str(error), getattr(error, "code_name", None)) from error
        except ConcurrencyLimitExceeded as error:
            QueryViewSet._raise_concurrency_throttled(cast(QueryViewSet, self), error)
        except AccountPersonsPropertyAccessError:
            raise PermissionDenied("You cannot filter or sort by this property.")
        if page is None:
            return Response({"detail": "Not found."}, status=404)
        return Response(AccountPersonsPageSerializer(page).data)

    @extend_schema(
        operation_id="accounts_persons_query_create",
        description="Run an account-user table query. Requires query, account, and person read scopes.",
        parameters=[OpenApiParameter("id", OpenApiTypes.UUID, OpenApiParameter.PATH)],
        request=AccountPersonsQueryRequest,
        responses={200: ActorsQueryResponse},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = self.get_model(request.data, AccountPersonsQueryRequest)
        if data.query.source.accountId != self.kwargs["id"]:
            raise ValidationError("The query account must match the account in the URL.")
        request.data.update(data.model_dump(mode="json", by_alias=True, exclude_none=True))
        return QueryViewSet.create(cast(QueryViewSet, self), request, *args, **kwargs)
