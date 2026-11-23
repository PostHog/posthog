import re
from datetime import timedelta
from decimal import Decimal
from typing import cast

from django.db.models import TextChoices

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import SessionAuthentication
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.managed_warehouse.backend.facade import console as console_facade
from products.managed_warehouse.backend.facade.contracts import (
    ControlPlaneNotConfiguredError,
    ControlPlaneRejectedError,
    ControlPlaneUnavailableError,
    ControlPlaneUpstreamError,
    InvalidLoginTeamError,
    LoginNotFoundError,
    ManagedWarehouseTrinoConnectionUnavailable,
    ProtectedLoginError,
    QueryNotFoundError,
    WarehouseNotFoundError,
)

# Trino query ids look like 20261120_101500_00001_abcde.
TRINO_QUERY_ID = re.compile(r"\d{8}_\d{6}_\d{5,}_[a-z0-9]{1,20}")

MIN_SCAN_CAP_BYTES = 1024**3
MAX_HISTORY_WINDOW = timedelta(days=31)
# The largest value of the BigIntegerField that stores the cap.
MAX_SCAN_CAP_BYTES = 2**63 - 1

# The SQL editor sets no query length limit, so this only bounds the request body.
MAX_ESTIMATE_QUERY_LENGTH = 100_000

# Same shape as hogtower accepts for a login name.
LOGIN_USERNAME = r"[A-Za-z0-9_][A-Za-z0-9_-]{0,62}"


class UsagePeriod(TextChoices):
    CURRENT_MONTH = "current_month", "Current month"
    LAST_MONTH = "last_month", "Last month"


class UsageGroupBy(TextChoices):
    SOURCE = "source", "Source"
    PRINCIPAL = "principal", "Principal"
    TEAM = "team", "Project"


class QueryHistoryState(TextChoices):
    FINISHED = "FINISHED", "Finished"
    FAILED = "FAILED", "Failed"


class LoginMode(TextChoices):
    READER = "reader", "Read only"
    USER = "user", "Read and write"


class LoginKind(TextChoices):
    ROOT = "root", "Root"
    PROJECT_READER = "project_reader", "Project, read only"
    PROJECT_USER = "project_user", "Project, read and write"
    OTHER = "other", "Other"


class ConsoleErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="What went wrong and what to do next.")


class UsageQuerySerializer(serializers.Serializer):
    period = serializers.ChoiceField(
        choices=UsagePeriod.choices, default=UsagePeriod.CURRENT_MONTH, help_text="UTC calendar month to report."
    )
    group_by = serializers.ChoiceField(
        choices=UsageGroupBy.choices, default=UsageGroupBy.SOURCE, help_text="How to break the compute spend down."
    )


class UsageComputeSerializer(serializers.Serializer):
    billable_bytes = serializers.IntegerField(
        help_text="Bytes billed for compute this period, failed queries included."
    )
    failed_billable_bytes = serializers.IntegerField(
        help_text="The part of the billed bytes that failed or was canceled."
    )
    logical_bytes = serializers.IntegerField(help_text="Logical bytes scanned this period.")
    queries = serializers.IntegerField(help_text="Number of queries run this period.")
    free_bytes = serializers.IntegerField(help_text="Billable bytes included free each month.")
    estimated_cost_usd = serializers.DecimalField(
        max_digits=20, decimal_places=6, help_text="Estimated compute cost in USD after the free tier."
    )


class UsageStorageSerializer(serializers.Serializer):
    gib_months = serializers.DecimalField(
        max_digits=24, decimal_places=6, help_text="Storage used this period, in GiB-months."
    )
    average_bytes = serializers.IntegerField(help_text="Average bytes stored over the period.")
    free_gib_months = serializers.DecimalField(
        max_digits=24, decimal_places=6, help_text="GiB-months of storage included free each month."
    )
    estimated_cost_usd = serializers.DecimalField(
        max_digits=20, decimal_places=6, help_text="Estimated storage cost in USD after the free tier."
    )


class UsageDailySerializer(serializers.Serializer):
    date = serializers.DateField(help_text="UTC day.")
    billable_bytes = serializers.IntegerField(help_text="Bytes billed for compute that day.")
    queries = serializers.IntegerField(help_text="Number of queries run that day.")
    storage_average_bytes = serializers.IntegerField(help_text="Average bytes stored that day.")


class UsageBreakdownSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Raw group key: a client source, a Trino principal, or a project id.")
    label = serializers.CharField(help_text="Readable name for the key.")
    queries = serializers.IntegerField(help_text="Number of queries in the group.")
    billable_bytes = serializers.IntegerField(help_text="Bytes billed for compute in the group.")
    estimated_cost_share_usd = serializers.DecimalField(
        max_digits=20,
        decimal_places=6,
        help_text="The group's share of the compute cost after the free tier, in proportion to billable bytes.",
    )


class UsageBudgetSerializer(serializers.Serializer):
    monthly_budget_usd = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True, help_text="Monthly budget in USD, or null when none is set."
    )
    share_used = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        allow_null=True,
        help_text="Estimated spend divided by the budget (1 is the whole budget), or null without a budget.",
    )


class UsageSummarySerializer(serializers.Serializer):
    period_start = serializers.DateField(help_text="First day of the period.")
    period_end = serializers.DateField(help_text="First day after the period.")
    compute = UsageComputeSerializer(help_text="Compute usage and estimated cost.")
    storage = UsageStorageSerializer(help_text="Storage usage and estimated cost.")
    total_estimated_cost_usd = serializers.DecimalField(
        max_digits=20, decimal_places=6, help_text="Estimated compute plus storage cost so far this period, in USD."
    )
    forecast_total_usd = serializers.DecimalField(
        max_digits=20,
        decimal_places=6,
        allow_null=True,
        help_text="Estimated cost for the whole month at the current pace. Null unless the period is the current month.",
    )
    daily = UsageDailySerializer(many=True, help_text="One entry for every day of the period up to today.")
    breakdown = UsageBreakdownSerializer(many=True, help_text="The 20 biggest groups, plus an Other row for the rest.")
    budget = UsageBudgetSerializer(help_text="Spend against the monthly budget.")


class QueryHistoryQuerySerializer(serializers.Serializer):
    # `from` is a Python keyword, so the field goes into the class namespace by name.
    vars()["from"] = serializers.DateTimeField(required=False, help_text="Only queries created at or after this time.")
    to = serializers.DateTimeField(required=False, help_text="Only queries created before this time.")
    principal = serializers.CharField(required=False, help_text="Only queries run by this Trino principal.")
    source = serializers.CharField(required=False, help_text="Only queries from this client source.")
    state = serializers.ChoiceField(
        choices=QueryHistoryState.choices, required=False, help_text="Only queries that finished or failed."
    )
    team_id = serializers.IntegerField(required=False, help_text="Only queries run for this project.")
    limit = serializers.IntegerField(required=False, min_value=1, max_value=200, help_text="Page size.")
    cursor = serializers.CharField(
        required=False, help_text="Cursor for the next page. Use next_cursor of the previous page."
    )

    def validate(self, attrs: dict) -> dict:
        start, end = attrs.get("from"), attrs.get("to")
        if start and end and end - start > MAX_HISTORY_WINDOW:
            raise serializers.ValidationError("The time range can span at most 31 days.")
        return attrs


class QueryHistoryRowSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Row id, used as the page cursor.")
    query_id = serializers.CharField(help_text="Trino query id.")
    principal = serializers.CharField(help_text="Trino user that ran the query.")
    principal_label = serializers.CharField(help_text="Readable name for the principal.")
    team_id = serializers.IntegerField(allow_null=True, help_text="Project the query ran for, when known.")
    source = serializers.CharField(help_text="Client source that sent the query.")
    source_label = serializers.CharField(help_text="Readable name for the source.")
    state = serializers.ChoiceField(choices=QueryHistoryState.choices, help_text="Final Trino state.")
    error_code = serializers.CharField(allow_null=True, help_text="Trino error code of a failed query.")
    error_type = serializers.CharField(allow_null=True, help_text="Trino error type of a failed query.")
    created_at = serializers.DateTimeField(allow_null=True, help_text="When the query was created.")
    completed_at = serializers.DateTimeField(allow_null=True, help_text="When the query completed.")
    elapsed_ms = serializers.IntegerField(allow_null=True, help_text="Wall time in milliseconds.")
    queued_ms = serializers.IntegerField(allow_null=True, help_text="Time spent queued in milliseconds.")
    logical_bytes_scanned = serializers.IntegerField(help_text="Logical bytes the query scanned.")
    billable = serializers.BooleanField(help_text="Whether the query counts toward billing.")
    billable_bytes = serializers.IntegerField(
        help_text="Bytes billed for the query: the scanned bytes when billable, else 0."
    )
    cpu_seconds = serializers.FloatField(allow_null=True, help_text="CPU seconds the query used.")
    query = serializers.CharField(
        allow_null=True,
        help_text="SQL text of the query. Null when you cannot access the project the query ran for.",
    )
    estimated_cost_usd = serializers.DecimalField(
        max_digits=20,
        decimal_places=6,
        help_text="Estimated cost of the query at the per-TiB price. The monthly free tier is not applied per query.",
    )


class QueryHistoryResponseSerializer(serializers.Serializer):
    queries = QueryHistoryRowSerializer(many=True, help_text="Queries, newest first.")
    next_cursor = serializers.CharField(
        allow_null=True, help_text="Pass as cursor to get the next page. Null on the last page."
    )


class CancelQueryRequestSerializer(serializers.Serializer):
    principal = serializers.CharField(
        required=False,
        help_text="The principal the caller saw on the query. Members who are not organization admins "
        "may only cancel queries of their own SQL editor principal.",
    )


class CancelQueryResponseSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Always cancel_requested. Trino stops the query shortly after.")


class StorageTableSerializer(serializers.Serializer):
    schema = serializers.CharField(help_text="Schema the table lives in.")
    table = serializers.CharField(help_text="Table name.")
    data_bytes = serializers.IntegerField(help_text="Bytes of live data files.")
    delete_bytes = serializers.IntegerField(help_text="Bytes of delete files not yet compacted away.")
    file_count = serializers.IntegerField(help_text="Number of data files.")
    row_count = serializers.IntegerField(help_text="Number of rows.")
    last_modified_at = serializers.DateTimeField(allow_null=True, help_text="When the table last changed.")


class StorageResponseSerializer(serializers.Serializer):
    tables = StorageTableSerializer(many=True, help_text="Storage per table.")
    total_bytes = serializers.IntegerField(help_text="Bytes stored across all tables.")
    pending_deletion_files = serializers.IntegerField(help_text="Files waiting to be deleted from object storage.")
    read_at = serializers.DateTimeField(allow_null=True, help_text="When the catalog was read.")
    maintenance = serializers.DictField(
        child=serializers.JSONField(),
        allow_null=True,
        help_text="Maintenance status as the control plane reports it. Null when it could not be read.",
    )


class WarehouseLoginSerializer(serializers.Serializer):
    username = serializers.CharField(help_text="Trino user name of the login.")
    kind = serializers.ChoiceField(
        choices=LoginKind.choices,
        help_text="Whether this is the root login, a project login, or another login. Only project logins can be changed.",
    )
    team_id = serializers.IntegerField(allow_null=True, help_text="Project a project login is limited to.")
    scope_label = serializers.CharField(help_text="What the login can do, for example Read only · Project name.")
    disabled = serializers.BooleanField(help_text="Whether the login is switched off.")
    created_at = serializers.DateTimeField(allow_null=True, help_text="When the login was created.")
    updated_at = serializers.DateTimeField(allow_null=True, help_text="When the login last changed.")
    queries_30d = serializers.IntegerField(help_text="Queries the login ran in the last 30 days.")
    billable_bytes_30d = serializers.IntegerField(help_text="Bytes billed to the login in the last 30 days.")


class WarehouseLoginListSerializer(serializers.Serializer):
    logins = WarehouseLoginSerializer(many=True, help_text="Every login of the warehouse, by name.")


class CreateLoginRequestSerializer(serializers.Serializer):
    team_id = serializers.IntegerField(min_value=1, help_text="Project the login is limited to.")
    mode = serializers.ChoiceField(
        choices=LoginMode.choices,
        help_text="reader can only read the project's data. user can also write to it.",
    )


class UpdateLoginRequestSerializer(serializers.Serializer):
    disabled = serializers.BooleanField(help_text="True switches the login off. False switches it back on.")


class WarehouseLoginCredentialSerializer(serializers.Serializer):
    login = WarehouseLoginSerializer(help_text="The login.")
    password = serializers.CharField(
        help_text="The new password. It is shown once and PostHog does not keep it, so copy it now."
    )


class ConsoleSettingsSerializer(serializers.Serializer):
    max_scan_bytes_per_query = serializers.IntegerField(
        allow_null=True,
        help_text="Largest number of bytes a single SQL editor query may scan, or null for no cap.",
    )
    monthly_budget_usd = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True, help_text="Monthly budget in USD, or null for none."
    )


class ConsoleSettingsUpdateSerializer(serializers.Serializer):
    max_scan_bytes_per_query = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=MIN_SCAN_CAP_BYTES,
        max_value=MAX_SCAN_CAP_BYTES,
        help_text="Largest number of bytes a single SQL editor query may scan, at least 1 GiB. Null removes the cap.",
    )
    monthly_budget_usd = serializers.DecimalField(
        required=False,
        allow_null=True,
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        help_text="Monthly budget in USD, more than 0. Null removes the budget.",
    )


class QueryEstimateWarning(TextChoices):
    NO_FILTER_ON_LARGE_TABLE = "no_filter_on_large_table", "No filter on a large table"
    EXCEEDS_CAP = "exceeds_cap", "Exceeds the per-query cap"
    SIZE_UNKNOWN = "size_unknown", "Size unknown"


class QueryEstimateRequestSerializer(serializers.Serializer):
    query = serializers.CharField(
        max_length=MAX_ESTIMATE_QUERY_LENGTH, help_text="The SQL editor query to estimate, HogQL or raw Trino SQL."
    )
    send_raw_query = serializers.BooleanField(
        default=False, help_text="True when the query is raw Trino SQL. False when it is HogQL."
    )
    variables = serializers.DictField(
        child=serializers.JSONField(),
        required=False,
        allow_null=True,
        help_text="SQL editor variables by id, in the shape a HogQL query takes. They fill the {variables} placeholders.",
    )
    filters = serializers.DictField(
        child=serializers.JSONField(),
        required=False,
        allow_null=True,
        help_text="HogQL filters, in the shape a HogQL query takes. They fill the {filters} placeholders.",
    )


class QueryEstimateTableSerializer(serializers.Serializer):
    catalog = serializers.CharField(help_text="Trino catalog the query reads.")
    schema = serializers.CharField(help_text="Schema the table lives in.")
    table = serializers.CharField(help_text="Table name.")
    size_bytes = serializers.IntegerField(
        allow_null=True, help_text="Bytes of live data files, or null when the table is not in the storage listing."
    )
    has_filter = serializers.BooleanField(help_text="Whether the query limits at least one column of this table.")


class QueryEstimateResponseSerializer(serializers.Serializer):
    tables = QueryEstimateTableSerializer(many=True, help_text="Tables the query reads.")
    upper_bound_bytes = serializers.IntegerField(
        allow_null=True,
        help_text="Most bytes the query can scan: the stored size of every table it reads. Null when no table size is known.",
    )
    estimated_cost_usd = serializers.DecimalField(
        max_digits=20,
        decimal_places=6,
        allow_null=True,
        help_text="Compute cost of the upper bound at the marginal rate, before the monthly free tier. Null when unknown.",
    )
    cap_bytes = serializers.IntegerField(
        allow_null=True, help_text="The organization's per-query scan cap, or null for no cap."
    )
    exceeds_cap = serializers.BooleanField(help_text="Whether the upper bound is above the cap.")
    complete = serializers.BooleanField(
        help_text="False when a table has an unknown size, so the upper bound may be too low."
    )
    warnings = serializers.ListField(
        child=serializers.ChoiceField(choices=QueryEstimateWarning.choices),
        help_text="Things to check before running the query.",
    )


# An empty message means the error's own text is safe to show.
_ERROR_STATUS: tuple[tuple[type[Exception], int, str], ...] = (
    (ExposedHogQLError, status.HTTP_400_BAD_REQUEST, ""),
    (
        ManagedWarehouseTrinoConnectionUnavailable,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "The warehouse is not ready for queries. Try again in a minute.",
    ),
    (ControlPlaneRejectedError, status.HTTP_400_BAD_REQUEST, ""),
    (ProtectedLoginError, status.HTTP_400_BAD_REQUEST, ""),
    (InvalidLoginTeamError, status.HTTP_400_BAD_REQUEST, ""),
    (LoginNotFoundError, status.HTTP_404_NOT_FOUND, "The warehouse has no login with that name."),
    (ControlPlaneNotConfiguredError, status.HTTP_501_NOT_IMPLEMENTED, "The managed warehouse is not available here."),
    (WarehouseNotFoundError, status.HTTP_404_NOT_FOUND, "This organization has no managed warehouse yet."),
    (QueryNotFoundError, status.HTTP_404_NOT_FOUND, "The query was not found or has already finished."),
    (
        ControlPlaneUnavailableError,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "The warehouse is temporarily unavailable. Try again in a minute.",
    ),
    (
        ControlPlaneUpstreamError,
        status.HTTP_502_BAD_GATEWAY,
        "The managed warehouse did not respond. Try again in a minute.",
    ),
)

_ERRORS = {
    status.HTTP_404_NOT_FOUND: OpenApiResponse(
        response=ConsoleErrorSerializer, description="Not found or not enabled."
    ),
    status.HTTP_501_NOT_IMPLEMENTED: OpenApiResponse(
        response=ConsoleErrorSerializer, description="No managed warehouse control plane is configured."
    ),
    status.HTTP_502_BAD_GATEWAY: OpenApiResponse(
        response=ConsoleErrorSerializer, description="The control plane failed."
    ),
    status.HTTP_503_SERVICE_UNAVAILABLE: OpenApiResponse(
        response=ConsoleErrorSerializer, description="The control plane or catalog is unavailable."
    ),
}


def _credential_response(credential: object) -> Response:
    response = Response(WarehouseLoginCredentialSerializer(credential).data)
    # The response carries a password, so no cache or proxy may keep it.
    response["Cache-Control"] = "no-store"
    return response


def _error_response(error: Exception) -> Response:
    for error_type, code, message in _ERROR_STATUS:
        if isinstance(error, error_type):
            return Response({"error": message or str(error)}, status=code)
    raise error


class ManagedWarehouseConsoleViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Usage, estimated spend, query history and storage of the organization's managed warehouse."""

    # Same scope handling as DataWarehouseViewSet: reads need viewer access, writes editor access.
    # Every action is organization-wide, so the resource-level rule applies to the whole collection.
    scope_object = "warehouse_view"
    requires_resource_level_access = True
    serializer_class = _FallbackSerializer

    def dangerously_get_required_scopes(self, request: Request, view: viewsets.ViewSet) -> list[str] | None:
        # GET and PATCH settings share one route, so the action's own scope cannot tell them apart.
        if self.action == "console_settings":
            return ["warehouse_view:read"]
        if self.action == "update_console_settings":
            return ["warehouse_view:write"]
        if self.action == "logins":
            return ["warehouse_view:read"]
        if self.action in ("create_login", "update_login", "delete_login"):
            return ["warehouse_view:write"]
        return None

    @property
    def _organization_id(self) -> str:
        return str(self.team.organization_id)

    def _disabled_response(self) -> Response | None:
        if console_facade.is_console_enabled(self._organization_id):
            return None
        return Response({"error": "This feature is not enabled"}, status=status.HTTP_404_NOT_FOUND)

    def _is_organization_admin(self, request: Request) -> bool:
        if not request.user.is_authenticated:
            return False
        membership = OrganizationMembership.objects.filter(
            organization_id=self.team.organization_id, user=request.user
        ).first()
        return membership is not None and membership.effective_level >= OrganizationMembership.Level.ADMIN

    def _login_admin_gate(self, request: Request, *, changes_login: bool = False) -> Response | None:
        if (disabled := self._disabled_response()) is not None:
            return disabled
        # A login password is a long-lived credential. Only a signed-in browser session may mint,
        # rotate or change one, so a leaked API key or OAuth token cannot.
        if changes_login and not isinstance(request.successful_authenticator, SessionAuthentication):
            return Response(
                {"error": "Sign in to PostHog in your browser to manage warehouse logins"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not self._is_organization_admin(request):
            return self._admin_required_response("manage the logins of")
        return None

    def _admin_required_response(self, what: str) -> Response:
        return Response(
            {"error": f"Only organization admins can {what} the managed warehouse"},
            status=status.HTTP_403_FORBIDDEN,
        )

    @validated_request(
        query_serializer=UsageQuerySerializer,
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=UsageSummarySerializer, description="Usage and estimated spend for one month."
            ),
            **_ERRORS,
        },
        summary="Get managed warehouse usage",
        description="Compute and storage usage for a UTC calendar month, with estimated spend, a forecast "
        "for the current month and a breakdown by source, principal or project.",
    )
    @action(methods=["GET"], detail=False, required_scopes=["warehouse_view:read"])
    def usage(self, request: Request, **kwargs) -> Response:
        if (disabled := self._disabled_response()) is not None:
            return disabled
        query = cast(dict, request.validated_query_data)  # type: ignore[attr-defined]
        try:
            summary = console_facade.build_usage_summary(
                self._organization_id, period=query["period"], group_by=query["group_by"]
            )
        except Exception as error:
            return _error_response(error)
        return Response(UsageSummarySerializer(summary).data)

    @validated_request(
        query_serializer=QueryHistoryQuerySerializer,
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=QueryHistoryResponseSerializer, description="A page of finished queries."
            ),
            **_ERRORS,
        },
        summary="List managed warehouse query history",
        description="Finished queries of the organization's warehouse, newest first, each with an estimated cost.",
    )
    @action(methods=["GET"], detail=False, required_scopes=["warehouse_view:read"])
    def queries(self, request: Request, **kwargs) -> Response:
        if (disabled := self._disabled_response()) is not None:
            return disabled
        query = cast(dict, request.validated_query_data)  # type: ignore[attr-defined]
        try:
            page = console_facade.list_query_history(
                self._organization_id,
                date_from=query.get("from"),
                date_to=query.get("to"),
                principal=query.get("principal"),
                source=query.get("source"),
                state=query.get("state"),
                team_id=query.get("team_id"),
                limit=query.get("limit"),
                cursor=query.get("cursor"),
                # Members see every row of the organization, but SQL text only for projects they can access.
                redact_for_user=None if self._is_organization_admin(request) else cast(User, request.user),
            )
        except Exception as error:
            return _error_response(error)
        return Response(QueryHistoryResponseSerializer(page).data)

    @validated_request(
        request_serializer=CancelQueryRequestSerializer,
        responses={
            status.HTTP_202_ACCEPTED: OpenApiResponse(
                response=CancelQueryResponseSerializer, description="The cancel was requested."
            ),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                response=ConsoleErrorSerializer, description="The query id is not a Trino query id."
            ),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ConsoleErrorSerializer, description="The caller may not cancel this query."
            ),
            **_ERRORS,
        },
        summary="Cancel a managed warehouse query",
        description="Ask Trino to cancel a running query. Organization admins may cancel any query. "
        "Other members may cancel queries of their own SQL editor principal.",
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path=r"queries/(?P<query_id>[^/]+)/cancel",
        required_scopes=["warehouse_view:write"],
    )
    def cancel_query(self, request: Request, query_id: str, **kwargs) -> Response:
        if (disabled := self._disabled_response()) is not None:
            return disabled
        if not TRINO_QUERY_ID.fullmatch(query_id):
            return Response({"error": "That is not a valid Trino query id"}, status=status.HTTP_400_BAD_REQUEST)
        principal: str | None = None
        if not self._is_organization_admin(request):
            # A member may cancel only a query that runs as their own SQL editor principal. hogtower
            # checks the running query's Trino user against the principal we forward and answers 404
            # on a mismatch, so a wrong or borrowed principal cannot cancel someone else's query.
            principal = request.validated_data.get("principal", "")  # type: ignore[attr-defined]
            user = cast(User, request.user)
            if not console_facade.is_own_sql_editor_principal(
                principal or "", organization_id=self._organization_id, user_id=user.pk
            ):
                return self._admin_required_response("cancel other people's queries on")
        try:
            console_facade.cancel_query(self._organization_id, query_id, principal=principal)
        except Exception as error:
            return _error_response(error)
        return Response({"status": "cancel_requested"}, status=status.HTTP_202_ACCEPTED)

    @validated_request(
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=StorageResponseSerializer, description="Storage per table and maintenance status."
            ),
            **_ERRORS,
        },
        summary="Get managed warehouse storage",
        description="Storage per table from the catalog, and the read-only maintenance status.",
    )
    @action(methods=["GET"], detail=False, required_scopes=["warehouse_view:read"])
    def storage(self, request: Request, **kwargs) -> Response:
        if (disabled := self._disabled_response()) is not None:
            return disabled
        try:
            overview = console_facade.get_storage_overview(self._organization_id)
        except Exception as error:
            return _error_response(error)
        return Response(StorageResponseSerializer(overview).data)

    @validated_request(
        request_serializer=QueryEstimateRequestSerializer,
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=QueryEstimateResponseSerializer, description="The most the query can scan, and its cost."
            ),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                response=ConsoleErrorSerializer, description="The query is invalid or not allowed."
            ),
            **_ERRORS,
        },
        summary="Estimate a managed warehouse query",
        description="Plan the query without running it and report the tables it reads, the most it can scan "
        "and the compute cost of that, before the monthly free tier.",
    )
    @action(methods=["POST"], detail=False, required_scopes=["warehouse_view:read"])
    def estimate(self, request: Request, **kwargs) -> Response:
        if (disabled := self._disabled_response()) is not None:
            return disabled
        data = request.validated_data  # type: ignore[attr-defined]
        try:
            result = console_facade.estimate_managed_trino_query(
                self.team,
                cast(User, request.user),
                query=data["query"],
                send_raw_query=data["send_raw_query"],
                variables=data.get("variables"),
                filters=data.get("filters"),
            )
        except Exception as error:
            return _error_response(error)
        return Response(QueryEstimateResponseSerializer(result).data)

    @validated_request(
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=ConsoleSettingsSerializer, description="Spend settings of the organization."
            ),
            status.HTTP_404_NOT_FOUND: _ERRORS[status.HTTP_404_NOT_FOUND],
        },
        summary="Get managed warehouse spend settings",
        description="The per-query scan cap and monthly budget of the organization's warehouse.",
    )
    # No required_scopes here: the PATCH mapping would inherit them. dangerously_get_required_scopes splits them.
    @action(methods=["GET"], detail=False, url_path="settings")
    def console_settings(self, request: Request, **kwargs) -> Response:
        if (disabled := self._disabled_response()) is not None:
            return disabled
        return Response(ConsoleSettingsSerializer(console_facade.get_console_settings(self._organization_id)).data)

    @validated_request(
        request_serializer=ConsoleSettingsUpdateSerializer,
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=ConsoleSettingsSerializer, description="The settings after the update."
            ),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ConsoleErrorSerializer, description="Only organization admins can change the settings."
            ),
            status.HTTP_404_NOT_FOUND: _ERRORS[status.HTTP_404_NOT_FOUND],
        },
        summary="Update managed warehouse spend settings",
        description="Change the per-query scan cap or monthly budget. Fields left out stay as they are.",
    )
    @console_settings.mapping.patch
    def update_console_settings(self, request: Request, **kwargs) -> Response:
        if (disabled := self._disabled_response()) is not None:
            return disabled
        if not self._is_organization_admin(request):
            return self._admin_required_response("change the spend settings of")
        updated = console_facade.update_console_settings(
            self._organization_id,
            changes=dict(request.validated_data),  # type: ignore[attr-defined]
        )
        return Response(ConsoleSettingsSerializer(updated).data)

    @validated_request(
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=WarehouseLoginListSerializer, description="The warehouse's logins with 30-day activity."
            ),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ConsoleErrorSerializer, description="Only organization admins can see logins."
            ),
            **_ERRORS,
        },
        summary="List managed warehouse logins",
        description="The Trino logins customers connect with, each with queries and billed bytes of the last 30 days.",
    )
    # No required_scopes here: the POST mapping would inherit them. dangerously_get_required_scopes splits them.
    @action(methods=["GET"], detail=False, url_path="logins")
    def logins(self, request: Request, **kwargs) -> Response:
        if (gate := self._login_admin_gate(request)) is not None:
            return gate
        try:
            logins = console_facade.list_logins(self._organization_id)
        except Exception as error:
            return _error_response(error)
        return Response(WarehouseLoginListSerializer({"logins": logins}).data)

    @validated_request(
        request_serializer=CreateLoginRequestSerializer,
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=WarehouseLoginCredentialSerializer, description="The login and its new password."
            ),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                response=ConsoleErrorSerializer, description="The project is not in this organization."
            ),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ConsoleErrorSerializer, description="Only organization admins can create logins."
            ),
            **_ERRORS,
        },
        summary="Create or rotate a managed warehouse project login",
        description="Create the project's Trino login for the mode, or give an existing one a new password. "
        "The password is in this response only.",
    )
    @logins.mapping.post
    def create_login(self, request: Request, **kwargs) -> Response:
        if (gate := self._login_admin_gate(request, changes_login=True)) is not None:
            return gate
        data = request.validated_data  # type: ignore[attr-defined]
        try:
            credential = console_facade.create_project_login(
                self._organization_id,
                team_id=data["team_id"],
                mode=data["mode"],
                acting_user_id=cast(User, request.user).pk,
            )
        except Exception as error:
            return _error_response(error)
        return _credential_response(credential)

    @validated_request(
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=WarehouseLoginCredentialSerializer, description="The login and its new password."
            ),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                response=ConsoleErrorSerializer, description="Only project logins can be changed here."
            ),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ConsoleErrorSerializer,
                description="Only organization admins signed in with a browser session can rotate logins.",
            ),
            **_ERRORS,
        },
        summary="Rotate a managed warehouse login password",
        description="Replace the login's password. The old one stops working. The new one is in this response only.",
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path=rf"logins/(?P<username>{LOGIN_USERNAME})/rotate",
        required_scopes=["warehouse_view:write"],
    )
    def rotate_login(self, request: Request, username: str, **kwargs) -> Response:
        if (gate := self._login_admin_gate(request, changes_login=True)) is not None:
            return gate
        try:
            credential = console_facade.rotate_login(
                self._organization_id, username, acting_user_id=cast(User, request.user).pk
            )
        except Exception as error:
            return _error_response(error)
        return _credential_response(credential)

    @validated_request(
        request_serializer=UpdateLoginRequestSerializer,
        responses={
            status.HTTP_200_OK: OpenApiResponse(response=WarehouseLoginSerializer, description="The login now."),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                response=ConsoleErrorSerializer, description="Only project logins can be changed here."
            ),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ConsoleErrorSerializer, description="Only organization admins can change logins."
            ),
            **_ERRORS,
        },
        summary="Switch a managed warehouse login on or off",
        description="Disable a login so it can no longer connect, or enable it again.",
    )
    # No required_scopes here: the DELETE mapping would inherit them. dangerously_get_required_scopes splits them.
    @action(methods=["PATCH"], detail=False, url_path=rf"logins/(?P<username>{LOGIN_USERNAME})")
    def update_login(self, request: Request, username: str, **kwargs) -> Response:
        if (gate := self._login_admin_gate(request, changes_login=True)) is not None:
            return gate
        try:
            login = console_facade.set_login_disabled(
                self._organization_id,
                username,
                disabled=request.validated_data["disabled"],  # type: ignore[attr-defined]
                acting_user_id=cast(User, request.user).pk,
            )
        except Exception as error:
            return _error_response(error)
        return Response(WarehouseLoginSerializer(login).data)

    @validated_request(
        responses={
            status.HTTP_204_NO_CONTENT: OpenApiResponse(description="The login was deleted."),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                response=ConsoleErrorSerializer, description="Only project logins can be changed here."
            ),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(
                response=ConsoleErrorSerializer, description="Only organization admins can delete logins."
            ),
            **_ERRORS,
        },
        summary="Delete a managed warehouse login",
        description="Delete a login. Anything still using its password stops connecting.",
    )
    @update_login.mapping.delete
    def delete_login(self, request: Request, username: str, **kwargs) -> Response:
        if (gate := self._login_admin_gate(request, changes_login=True)) is not None:
            return gate
        try:
            console_facade.delete_login(self._organization_id, username, acting_user_id=cast(User, request.user).pk)
        except Exception as error:
            return _error_response(error)
        return Response(status=status.HTTP_204_NO_CONTENT)
