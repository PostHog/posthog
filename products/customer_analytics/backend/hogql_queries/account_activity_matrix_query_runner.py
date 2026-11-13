from datetime import date, datetime, timedelta
from functools import cached_property
from typing import TYPE_CHECKING
from uuid import UUID

from posthog.schema import (
    AccountActivityMatrixCell,
    AccountActivityMatrixColumn,
    AccountActivityMatrixEmptyReason,
    AccountActivityMatrixQuery,
    AccountActivityMatrixQueryResponse,
    AccountActivityMatrixResult,
    AccountActivityMatrixRow,
    AccountActivityMatrixSeries,
    CachedAccountActivityMatrixQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.visitor import clone_expr

from posthog.models.group_usage_metric import GroupUsageMetric
from posthog.models.user import User
from posthog.week_start_day import WeekStartDay

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.actions.backend.facade.api import get_actions
from products.customer_analytics.backend.constants import ACCOUNT_ACTIVITY_MATRIX_QUERY_STATUS_LABEL_PREFIX
from products.customer_analytics.backend.hogql_queries.activity_base import (
    ActivityQueryRunner,
    activity_columns,
    is_uuid,
)
from products.customer_analytics.backend.logic.account_activity_access import get_account_activity_account
from products.customer_analytics.backend.models import Account

if TYPE_CHECKING:
    from products.actions.backend.facade.contracts import Action

DEFAULT_WEEKS = 8
MAX_WEEKS = 26
MAX_SERIES = 64

MetricWithFilter = tuple[GroupUsageMetric, ast.Expr]


class AccountActivityMatrixQueryRunner(ActivityQueryRunner[AccountActivityMatrixQueryResponse]):
    query: AccountActivityMatrixQuery
    cached_response: CachedAccountActivityMatrixQueryResponse

    def validate_query_runner_access(self, user: User) -> bool:
        get_account_activity_account(team=self.team, user=user, account_id=self.query.accountId)
        return True

    def get_cache_key_variant(self) -> str:
        try:
            get_account_activity_account(team=self.team, user=self.user, account_id=self.query.accountId)
        except UserAccessControlError:
            return f"{super().get_cache_key_variant()}_denied"
        return super().get_cache_key_variant()

    def query_status_labels(self) -> list[str]:
        return [
            *super().query_status_labels(),
            f"{ACCOUNT_ACTIVITY_MATRIX_QUERY_STATUS_LABEL_PREFIX}{self.query.accountId}",
        ]

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        try:
            payload["account_external_id"] = self._account.external_id
        except UserAccessControlError:
            payload["account_external_id"] = None
        payload["metric_fingerprints"] = sorted(
            (str(metric.id), metric.name, metric.math, metric.math_property or "", str(metric.filters))
            for metric in self._team_metrics
        )
        return payload

    def to_query(self) -> ast.SelectQuery:
        external_id, group_type_index = self._group_identity()
        metrics, _ = self._split_metrics()
        if not external_id or group_type_index is None or not metrics:
            return ast.SelectQuery.empty()
        return self._matrix_query(external_id, group_type_index, metrics)

    def _calculate(self) -> AccountActivityMatrixQueryResponse:
        columns = self._columns()
        external_id, group_type_index = self._group_identity()
        metrics, skipped = self._split_metrics()
        series = [AccountActivityMatrixSeries(key=str(metric.id), label=metric.name) for metric, _ in metrics]
        skipped_ids = [str(metric.id) for metric in skipped]

        if not external_id:
            return self._empty(columns, series, skipped_ids, AccountActivityMatrixEmptyReason.NO_EXTERNAL_ID)
        if group_type_index is None:
            return self._empty(columns, series, skipped_ids, AccountActivityMatrixEmptyReason.NO_GROUP_TYPE)
        if not metrics:
            return self._empty(columns, series, skipped_ids, AccountActivityMatrixEmptyReason.NO_METRICS)

        response = self._execute(
            "AccountActivityMatrixQuery", self._matrix_query(external_id, group_type_index, metrics)
        )

        totals: dict[str, int] = {}
        data: list[AccountActivityMatrixCell] = []
        for person_id, week, events, *values in response.results or []:
            row = str(person_id)
            totals[row] = totals.get(row, 0) + int(events)
            column = week.isoformat() if isinstance(week, date) else str(week)
            for (metric, _), value in zip(metrics, values):
                if value:
                    data.append(
                        AccountActivityMatrixCell(row=row, column=column, series=str(metric.id), value=float(value))
                    )

        ranked = sorted(totals, key=lambda person_id: (-totals[person_id], person_id))
        kept = ranked[: self._row_limit]
        kept_ids = set(kept)
        labels = self._person_labels(kept)
        return AccountActivityMatrixQueryResponse(
            results=AccountActivityMatrixResult(
                rows=[
                    AccountActivityMatrixRow(key=person_id, label=labels.get(person_id, person_id))
                    for person_id in kept
                ],
                columns=columns,
                series=series,
                data=[cell for cell in data if cell.row in kept_ids],
                truncated=len(ranked) > len(kept),
                skippedMetricIds=skipped_ids,
            ),
            hogql=response.hogql,
            timings=self.timings.to_list(),
            modifiers=self.modifiers,
        )

    def _empty(
        self,
        columns: list[AccountActivityMatrixColumn],
        series: list[AccountActivityMatrixSeries],
        skipped_ids: list[str],
        reason: AccountActivityMatrixEmptyReason,
    ) -> AccountActivityMatrixQueryResponse:
        return AccountActivityMatrixQueryResponse(
            results=AccountActivityMatrixResult(
                rows=[],
                columns=columns,
                series=series,
                data=[],
                truncated=False,
                skippedMetricIds=skipped_ids,
                emptyReason=reason,
            ),
            timings=self.timings.to_list(),
            modifiers=self.modifiers,
        )

    @cached_property
    def _account(self) -> Account:
        return get_account_activity_account(team=self.team, user=self.user, account_id=self.query.accountId)

    def _group_identity(self) -> tuple[str | None, int | None]:
        return self._account.external_id or None, self.team.customer_analytics_config.account_group_type_index

    @cached_property
    def _team_metrics(self) -> list[GroupUsageMetric]:
        metrics = GroupUsageMetric.objects.filter(team=self.team).only("id", "name", "filters", "math", "math_property")
        if self.query.metricIds is not None:
            metrics = metrics.filter(id__in=[metric_id for metric_id in self.query.metricIds if is_uuid(metric_id)])
        loaded = list(metrics.order_by("name", "id"))
        for metric in loaded:
            metric.team = self.team
        return loaded

    def _split_metrics(self) -> tuple[list[MetricWithFilter], list[GroupUsageMetric]]:
        eligible: list[MetricWithFilter] = []
        skipped: list[GroupUsageMetric] = []
        action_ids = {action_id for metric in self._team_metrics for action_id in metric.get_action_ids()}
        actions: dict[int, Action | None] = dict.fromkeys(action_ids)
        if action_ids:
            actions.update(
                {action.id: action for action in get_actions(action_ids=action_ids, project_id=self.team.project_id)}
            )
        test_account_filters: list[ast.Expr] | None = None
        for metric in self._team_metrics:
            if (
                len(eligible) >= MAX_SERIES
                or metric.is_data_warehouse
                or (metric.math == GroupUsageMetric.Math.SUM and not metric.math_property)
            ):
                skipped.append(metric)
                continue
            if metric.filters.get("filter_test_accounts", False) and test_account_filters is None:
                test_account_filters = metric.get_test_account_filters()
            filter_expr = metric.get_expr(actions, test_account_filters=test_account_filters)
            if filter_expr == ast.Constant(value=True):
                skipped.append(metric)
                continue
            eligible.append((metric, filter_expr))
        return eligible, skipped

    @cached_property
    def _now(self) -> datetime:
        return datetime.now(tz=self.team.timezone_info)

    @cached_property
    def _week_starts(self) -> list[date]:
        weeks = max(1, min(self.query.weeks or DEFAULT_WEEKS, MAX_WEEKS))
        today = self._now.date()
        first_weekday = 0 if self._week_start_day == WeekStartDay.MONDAY else 6
        current = today - timedelta(days=(today.weekday() - first_weekday) % 7)
        return [current - timedelta(weeks=offset) for offset in reversed(range(weeks))]

    def _columns(self) -> list[AccountActivityMatrixColumn]:
        return activity_columns(self._week_starts, self._week_starts[-1])

    def _events_where(self, external_id: str, group_type_index: int, metrics: list[MetricWithFilter]) -> ast.Expr:
        date_from = datetime.combine(self._week_starts[0], datetime.min.time(), tzinfo=self.team.timezone_info)
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[f"$group_{group_type_index}"]),
                    right=ast.Constant(value=external_id),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=date_from),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=self._now),
                ),
                ast.Or(exprs=[clone_expr(filter_expr) for _, filter_expr in metrics]),
            ]
        )

    def _matrix_query(
        self, external_id: str, group_type_index: int, metrics: list[MetricWithFilter]
    ) -> ast.SelectQuery:
        ranked_persons = ast.SelectQuery(
            select=[ast.Field(chain=["person_id"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=self._events_where(external_id, group_type_index, metrics),
            group_by=[ast.Field(chain=["person_id"])],
            order_by=[
                ast.OrderExpr(expr=ast.Call(name="count", args=[]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=["person_id"]), order="ASC"),
            ],
            limit=ast.Constant(value=self._row_limit + 1),
        )
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["person_id"]),
                ast.Alias(
                    alias="week",
                    expr=ast.Call(
                        name="toStartOfWeek",
                        args=[
                            ast.Field(chain=["timestamp"]),
                            ast.Constant(value=int(self._week_start_day.clickhouse_mode)),
                        ],
                    ),
                ),
                ast.Alias(alias="events", expr=ast.Call(name="count", args=[])),
                *(
                    ast.Alias(alias=f"s{index}", expr=_metric_value(metric, clone_expr(filter_expr)))
                    for index, (metric, filter_expr) in enumerate(metrics)
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    self._events_where(external_id, group_type_index, metrics),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=ast.Field(chain=["person_id"]),
                        right=ranked_persons,
                    ),
                ]
            ),
            group_by=[ast.Field(chain=["person_id"]), ast.Field(chain=["week"])],
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["person_id"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["week"]), order="ASC"),
            ],
            limit=ast.Constant(value=(self._row_limit + 1) * len(self._week_starts)),
        )

    def _person_labels(self, person_ids: list[str]) -> dict[str, str]:
        if not person_ids:
            return {}
        query = ast.SelectQuery(
            select=[
                ast.Field(chain=["id"]),
                ast.Call(
                    name="coalesce",
                    args=[ast.Field(chain=["properties", "email"]), ast.Field(chain=["properties", "name"])],
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["id"]),
                right=ast.Tuple(exprs=[ast.Constant(value=UUID(person_id)) for person_id in person_ids]),
            ),
            limit=ast.Constant(value=len(person_ids)),
        )
        response = self._execute("AccountActivityMatrixPersonLabels", query)
        return {str(person_id): str(label) for person_id, label in response.results or [] if label}


def _metric_value(metric: GroupUsageMetric, filter_expr: ast.Expr) -> ast.Expr:
    if metric.math == GroupUsageMetric.Math.SUM and metric.math_property:
        value = ast.Call(name="toFloat", args=[ast.Field(chain=["properties", metric.math_property])])
        return ast.Call(name="ifNull", args=[ast.Call(name="sumIf", args=[value, filter_expr]), ast.Constant(value=0)])
    return ast.Call(name="countIf", args=[filter_expr])
