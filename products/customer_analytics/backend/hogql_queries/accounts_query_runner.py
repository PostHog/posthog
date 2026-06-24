from posthog.schema import AccountsQuery, AccountsQueryResponse, CachedAccountsQueryResponse

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.errors import BaseHogQLError, ExposedHogQLError
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.errors import ExposedCHQueryError, InternalCHQueryError
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models import User
from posthog.rbac.user_access_control import UserAccessControl

from products.customer_analytics.backend.constants import BILLING_INVOICES_VIEW_NAME, BILLING_PICKER_COLUMNS

NAME_COLUMN = "name"

DEFAULT_COLUMNS = (NAME_COLUMN, "created_at")

DEFAULT_ORDER_BY = "created_at DESC"


def _normalize_order_clause(raw: str) -> str:
    """Allow Django-style `-col` shorthand alongside native HogQL `col DESC`."""
    stripped = raw.strip()
    if stripped.startswith("-"):
        return f"{stripped[1:].strip()} DESC"
    return stripped


# Account-properties JSON keys for the three assignable roles. The
# `allRolesUnassigned` filter ("Unassigned only") requires every one of these to
# be empty.
ROLE_JSON_KEYS = ("csm", "account_executive", "account_owner")

# Roles that count as "assigned" for the `assignedToUserIds` filter — an account
# is assigned to a user if they are its CSM or account executive.
ASSIGNED_ROLE_KEYS = ("csm", "account_executive")


class AccountsQueryRunner(AnalyticsQueryRunner[AccountsQueryResponse]):
    query: AccountsQuery
    cached_response: CachedAccountsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Metrics-only callers (just aggregations, no `select`) skip column
        # resolution. A combined query carries both `select` and `metrics`.
        self._metrics_only = bool(self.query.metrics) and not self.query.select

        self.columns: list[str] = []
        self._select_exprs: list[ast.Expr] = []
        # Whether the internal billing view exists for this team. Resolved once, and only when a
        # billing column is actually requested, so ordinary queries never pay the database-build
        # cost. Drives whether billing columns join the view or fall back to NULL.
        self._billing_view_available = False
        if not self._metrics_only:
            raw_selects = list(self.query.select) if self.query.select else list(DEFAULT_COLUMNS)
            if any(raw in BILLING_PICKER_COLUMNS for raw in raw_selects):
                self._billing_view_available = self._check_billing_view_available()
            seen: set[str] = set()
            for raw in raw_selects:
                column_name, expr = self._resolve_column(raw)
                if column_name in seen:
                    continue
                seen.add(column_name)
                self.columns.append(column_name)
                self._select_exprs.append(expr)
            if NAME_COLUMN not in seen:
                self.columns.insert(0, NAME_COLUMN)
                self._select_exprs.insert(0, self._name_tuple_expr())

        # Billing columns trigger a LEFT JOIN against the internal billing view in `to_query`.
        self._requested_billing_columns: list[str] = [c for c in self.columns if c in BILLING_PICKER_COLUMNS]

        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context,
            limit=self.query.limit,
            offset=self.query.offset,
        )

    def validate_query_runner_access(self, user: User) -> bool:
        return UserAccessControl(user=user, team=self.team).assert_access_level_for_resource(
            "customer_analytics", "viewer"
        )

    def _resolve_column(self, raw: str) -> tuple[str, ast.Expr]:
        if raw == NAME_COLUMN:
            return NAME_COLUMN, self._name_tuple_expr()
        if raw in BILLING_PICKER_COLUMNS:
            return raw, self._billing_column_expr(raw)
        expr = parse_expr(raw)
        column_name = expr.alias if isinstance(expr, ast.Alias) else raw
        return column_name, expr

    def _name_tuple_expr(self) -> ast.Expr:
        # Single cell carries the display name, external_id (for copy
        # affordance) and id (for row expansion / role updates), so the
        # frontend doesn't need to pin id and external_id as separate
        # hidden columns. Mirrors groups_query_runner's `group_name`.
        return ast.Alias(
            alias=NAME_COLUMN,
            expr=ast.Call(
                name="tuple",
                args=[
                    ast.Field(chain=["name"]),
                    ast.Field(chain=["external_id"]),
                    ast.Call(name="toString", args=[ast.Field(chain=["id"])]),
                ],
            ),
        )

    def _check_billing_view_available(self) -> bool:
        # The billing view is PostHog-internal; it only exists where the billing warehouse data is
        # synced. Build the team's HogQL database to check — done lazily (only when a billing column
        # is requested) since the build isn't free. Fail closed (NULL columns) on any error.
        try:
            database = Database.create_for(team=self.team, user=self.user)
            return database.has_table(BILLING_INVOICES_VIEW_NAME)
        except Exception:
            return False

    def _billing_column_expr(self, column: str) -> ast.Expr:
        # With the view present, read the column off the joined `billing` subquery (added in
        # `to_query`); without it, resolve to NULL so the column stays present but empty.
        if self._billing_view_available:
            return ast.Alias(alias=column, expr=ast.Field(chain=["billing", column]))
        return ast.Alias(alias=column, expr=ast.Constant(value=None))

    def _billing_join_expr(self) -> ast.JoinExpr:
        # Pre-aggregate the billing view to one current-calendar-month row per org, then LEFT JOIN
        # on the account's external_id. The GROUP BY keeps it one row per org, so the per-account
        # query stays one row per account (no GROUP BY there). Accounts with no invoice in the
        # current month don't match and surface NULL. Aliases must match BILLING_PICKER_COLUMNS.
        subquery = parse_select(
            """
            SELECT
                organization_id,
                sumIf(mrr, type NOT LIKE '%upcoming%') AS confirmed_mrr,
                sum(credits_used) AS credits_used
            FROM {view}
            WHERE toStartOfMonth(period_end) = toStartOfMonth(now())
            GROUP BY organization_id
            """,
            {"view": ast.Field(chain=[BILLING_INVOICES_VIEW_NAME])},
        )
        return ast.JoinExpr(
            table=subquery,
            alias="billing",
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                expr=parse_expr("billing.organization_id = accounts.external_id"),
                constraint_type="ON",
            ),
        )

    def _build_where_exprs(self) -> list[ast.Expr]:
        where_exprs: list[ast.Expr] = []

        if self.query.search and self.query.search.strip():
            pattern = f"%{self.query.search.strip()}%"
            where_exprs.append(
                parse_expr(
                    "accounts.name ILIKE {pattern} OR accounts.external_id ILIKE {pattern}",
                    {"pattern": ast.Constant(value=pattern)},
                )
            )

        if self.query.tagNames:
            where_exprs.append(self._tag_filter_expr(self.query.tagNames))

        if self.query.allRolesUnassigned:
            for json_key in ROLE_JSON_KEYS:
                where_exprs.append(self._role_id_isnull(json_key))

        if self.query.assignedToUserIds:
            where_exprs.append(self._assigned_to_users_expr(self.query.assignedToUserIds))

        if self.query.filterExpression and self.query.filterExpression.strip():
            where_exprs.append(parse_expr(self.query.filterExpression))

        return where_exprs

    def to_query(self) -> ast.SelectQuery:
        where_exprs = self._build_where_exprs()
        order_clauses = self.query.orderBy or [DEFAULT_ORDER_BY]

        select_from = ast.JoinExpr(
            table=ast.Field(chain=["system", "accounts"]),
            alias="accounts",
        )
        if self._requested_billing_columns and self._billing_view_available:
            select_from.next_join = self._billing_join_expr()

        return ast.SelectQuery(
            select=self._select_exprs,
            select_from=select_from,
            where=ast.And(exprs=where_exprs) if where_exprs else None,
            order_by=[parse_order_expr(_normalize_order_clause(c), timings=self.timings) for c in order_clauses],
        )

    def _to_metrics_query(self, metrics: list[str]) -> ast.SelectQuery:
        where_exprs = self._build_where_exprs()
        select_exprs = [parse_expr(expr) for expr in metrics]
        return ast.SelectQuery(
            select=select_exprs,
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["system", "accounts"]),
                alias="accounts",
            ),
            where=ast.And(exprs=where_exprs) if where_exprs else None,
        )

    def _tag_filter_expr(self, tag_names: list[str]) -> ast.Expr:
        subquery = parse_select(
            """
            SELECT ti.account_id
            FROM system._account_tagged_items AS ti
            INNER JOIN system.tags AS t ON t.id = ti.tag_id
            WHERE t.name IN {tag_names}
            """,
            {"tag_names": ast.Constant(value=list(tag_names))},
        )
        return parse_expr("id IN {subquery}", {"subquery": subquery})

    def _role_filter_expr(self, json_key: str, value: object) -> ast.Expr | None:
        if not value:
            return None
        raw_values = value if isinstance(value, list) else [value]
        user_ids: list[int] = []
        for raw in raw_values:
            if isinstance(raw, int):
                user_ids.append(raw)
            elif isinstance(raw, str):
                try:
                    user_ids.append(int(raw))
                except ValueError:
                    continue
        if not user_ids:
            return None
        return parse_expr(
            "JSONExtract(properties, {role_key}, 'id', 'Nullable(Int64)') IN {user_ids}",
            {
                "role_key": ast.Constant(value=json_key),
                "user_ids": ast.Constant(value=user_ids),
            },
        )

    def _role_id_isnull(self, json_key: str) -> ast.Expr:
        return parse_expr(
            "isNull(JSONExtract(properties, {role_key}, 'id', 'Nullable(Int64)'))",
            {"role_key": ast.Constant(value=json_key)},
        )

    def _assigned_to_users_expr(self, user_ids: list[int]) -> ast.Expr:
        # OR over the CSM/AE roles: an account is "assigned to" a user if they
        # hold either role. Explicit ids (not the requester) so a shared URL
        # filtered by "my accounts" resolves to the same accounts for every viewer.
        role_exprs: list[ast.Expr] = []
        for json_key in ASSIGNED_ROLE_KEYS:
            role_expr = self._role_filter_expr(json_key, user_ids)
            if role_expr is not None:
                role_exprs.append(role_expr)
        if not role_exprs:
            return ast.Constant(value=False)
        return ast.Or(exprs=role_exprs)

    def _calculate(self) -> AccountsQueryResponse:
        metrics_results = self._compute_metrics_results(self.query.metrics) if self.query.metrics else None

        if self._metrics_only:
            return AccountsQueryResponse(
                kind="AccountsQuery",
                columns=[],
                results=[],
                types=[],
                metricsResults=metrics_results,
                hogql="",
                modifiers=self.modifiers,
                limit=self.query.limit or 0,
                offset=self.query.offset or 0,
            )

        response = self.paginator.execute_hogql_query(
            query_type="AccountsQuery",
            query=self.to_query(),
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
        )

        name_index = self.columns.index(NAME_COLUMN)
        results = [
            [
                {"name": cell[0], "external_id": cell[1], "id": cell[2]} if index == name_index else cell
                for index, cell in enumerate(row)
            ]
            for row in self.paginator.results
        ]

        return AccountsQueryResponse(
            kind="AccountsQuery",
            columns=list(self.columns),
            results=results,
            types=[t for _, t in response.types] if response.types else [],
            metricsResults=metrics_results,
            hogql=response.hogql or "",
            timings=response.timings,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def _compute_metrics_results(self, metrics: list[str]) -> list[float | int | None]:
        try:
            response = self._execute_metrics_query(metrics)
        except (InternalCHQueryError, BaseHogQLError) as error:
            raise self._metric_evaluation_error(metrics, error) from error

        row = response.results[0] if response.results else []
        metrics_results: list[float | int | None] = [
            (value if isinstance(value, (int, float)) else None) for value in row
        ]
        while len(metrics_results) < len(metrics):
            metrics_results.append(None)
        return metrics_results

    def _execute_metrics_query(self, metrics: list[str]):
        return execute_hogql_query(
            query_type="AccountsMetricsQuery",
            query=self._to_metrics_query(metrics),
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
        )

    def _metric_evaluation_error(self, metrics: list[str], error: Exception) -> ExposedHogQLError:
        culprits = self._isolate_failing_metrics(metrics) if len(metrics) > 1 else list(metrics)
        listed = ", ".join(f"`{expr}`" for expr in (culprits or metrics))
        plural = "s" if len(culprits or metrics) > 1 else ""
        detail = (
            f"Could not evaluate overview tile metric{plural}: {listed}. "
            "Check that any referenced column exists and is numeric "
            "(data warehouse columns must be synced)."
        )
        if isinstance(error, (ExposedHogQLError, ExposedCHQueryError)):
            detail = f"{detail} {error}"
        return ExposedHogQLError(detail)

    def _isolate_failing_metrics(self, metrics: list[str]) -> list[str]:
        """Re-run each metric on its own (error path only) to name the offenders."""
        failing: list[str] = []
        for expr in metrics:
            try:
                self._execute_metrics_query([expr])
            except Exception:
                failing.append(expr)
        return failing
