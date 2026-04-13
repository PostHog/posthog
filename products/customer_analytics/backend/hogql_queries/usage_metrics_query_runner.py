from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import cached_property
from zoneinfo import ZoneInfo

from posthog.schema import CachedUsageMetricsQueryResponse, UsageMetric, UsageMetricsQuery, UsageMetricsQueryResponse

from posthog.hogql import ast

from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models.group_usage_metric import GroupUsageMetric


class UsageMetricsQueryRunner(AnalyticsQueryRunner[UsageMetricsQueryResponse]):
    query: UsageMetricsQuery
    cached_response: CachedUsageMetricsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self._is_group_query and not self._is_person_query:
            raise ValueError("UsageMetricsQuery must have either group_key or person_id")
        if self._is_group_query and self._is_person_query:
            raise ValueError("UsageMetricsQuery must have either group_key or person_id, not both")

    @property
    def _is_group_query(self) -> bool:
        return bool(self.query.group_key and self.query.group_type_index is not None)

    @property
    def _is_person_query(self) -> bool:
        return bool(self.query.person_id)

    def _calculate(self):
        from posthog.hogql.query import execute_hogql_query

        interval_groups = self._group_metrics_by_interval(self._usage_metrics)

        if not interval_groups:
            return UsageMetricsQueryResponse(results=[], modifiers=self.modifiers)

        date_to = datetime.now(tz=ZoneInfo("UTC"))
        all_results: list[UsageMetric] = []
        last_hogql: str | None = None
        all_timings = list(self.timings.to_list())

        for interval, group in interval_groups.items():
            query = self._build_interval_group_query(interval, group, date_to=date_to)

            with self.timings.measure(f"usage_metrics_interval_{interval}_execute"):
                response = execute_hogql_query(
                    query_type="usage_metrics_query",
                    query=query,
                    team=self.team,
                    timings=self.timings,
                    modifiers=self.modifiers,
                )

            last_hogql = response.hogql
            if response.timings:
                all_timings.extend(response.timings)

            with self.timings.measure(f"usage_metrics_interval_{interval}_post_process"):
                results = self._process_group_results(response, interval, group, date_to=date_to)
                all_results.extend(results)

        all_results.sort(key=lambda x: x.name, reverse=True)

        return UsageMetricsQueryResponse(
            results=all_results,
            timings=all_timings or None,
            hogql=last_hogql,
            modifiers=self.modifiers,
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        interval_groups = self._group_metrics_by_interval(self._usage_metrics)

        if not interval_groups:
            from posthog.hogql.database.models import UnknownDatabaseField

            return ast.SelectQuery.empty(columns={"day": UnknownDatabaseField(name="day")})

        date_to = datetime.now(tz=ZoneInfo("UTC"))
        queries = [
            self._build_interval_group_query(interval, group, date_to=date_to)
            for interval, group in interval_groups.items()
        ]

        if len(queries) == 1:
            return queries[0]
        return ast.SelectSetQuery.create_from_queries(queries=queries, set_operator="UNION ALL")

    @cached_property
    def _usage_metrics(self) -> list[GroupUsageMetric]:
        """
        Fetch all metrics for the team, regardless of group_type_index.
        The model conception was too coupled to groups, we'll need to make it group-agnostic to support person-level
        metrics. For now, as a PoC, will simply ignore group_type_index.

        """
        with self.timings.measure("get_usage_metrics"):
            return list(
                GroupUsageMetric.objects.filter(team=self.team).only(
                    "id", "name", "format", "interval", "display", "filters", "math", "math_property"
                )
            )

    def _group_metrics_by_interval(
        self, metrics: list[GroupUsageMetric]
    ) -> dict[int, list[tuple[GroupUsageMetric, ast.Expr]]]:
        groups: dict[int, list[tuple[GroupUsageMetric, ast.Expr]]] = defaultdict(list)
        for metric in metrics:
            if metric.math == GroupUsageMetric.Math.SUM and not metric.math_property:
                continue
            with self.timings.measure("get_metric_filter_expr"):
                filter_expr = metric.get_expr()
            if filter_expr == ast.Constant(value=True):
                continue
            groups[metric.interval].append((metric, filter_expr))
        return dict(groups)

    def _build_interval_group_query(
        self, interval: int, group: list[tuple[GroupUsageMetric, ast.Expr]], date_to: datetime
    ) -> ast.SelectQuery:
        date_from = date_to - timedelta(days=interval)
        prev_date_from = date_to - 2 * timedelta(days=interval)

        current_condition = self._build_period_condition(date_from, date_to)
        previous_condition = self._build_period_condition(prev_date_from, date_from, upper_exclusive=True)

        select_exprs: list[ast.Expr] = [
            ast.Alias(
                alias="day",
                expr=ast.Call(
                    name="toStartOfDay",
                    args=[
                        ast.Call(name="toTimeZone", args=[ast.Field(chain=["timestamp"]), ast.Constant(value="UTC")])
                    ],
                ),
            ),
        ]

        for i, (metric, filter_expr) in enumerate(group):
            value_expr, prev_expr = self._build_conditional_aggregation(
                metric, filter_expr, current_condition, previous_condition
            )
            select_exprs.append(ast.Alias(alias=f"m{i}_value", expr=value_expr))
            select_exprs.append(ast.Alias(alias=f"m{i}_previous", expr=prev_expr))

        where_exprs: list[ast.Expr] = [
            self._get_entity_filter(),
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=prev_date_from),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=date_to),
            ),
        ]

        return ast.SelectQuery(
            select=select_exprs,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=where_exprs),
            group_by=[ast.Field(chain=["day"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["day"]), order="ASC")],
        )

    def _build_period_condition(
        self, period_from: datetime, period_to: datetime, upper_exclusive: bool = False
    ) -> ast.Expr:
        upper_op = ast.CompareOperationOp.Lt if upper_exclusive else ast.CompareOperationOp.LtEq
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=period_from),
                ),
                ast.CompareOperation(
                    op=upper_op,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=period_to),
                ),
            ]
        )

    def _build_conditional_aggregation(
        self,
        metric: GroupUsageMetric,
        filter_expr: ast.Expr,
        current_condition: ast.Expr,
        previous_condition: ast.Expr,
    ) -> tuple[ast.Expr, ast.Expr]:
        current_cond = ast.And(exprs=[filter_expr, current_condition])
        previous_cond = ast.And(exprs=[filter_expr, previous_condition])

        if metric.math == GroupUsageMetric.Math.SUM:
            prop_as_float = ast.Call(name="toFloat", args=[ast.Field(chain=["properties", metric.math_property])])
            return (
                ast.Call(
                    name="ifNull",
                    args=[ast.Call(name="sumIf", args=[prop_as_float, current_cond]), ast.Constant(value=0)],
                ),
                ast.Call(
                    name="ifNull",
                    args=[ast.Call(name="sumIf", args=[prop_as_float, previous_cond]), ast.Constant(value=0)],
                ),
            )

        return (
            ast.Call(name="toFloat", args=[ast.Call(name="countIf", args=[current_cond])]),
            ast.Call(name="toFloat", args=[ast.Call(name="countIf", args=[previous_cond])]),
        )

    def _process_group_results(
        self,
        response,
        interval: int,
        group: list[tuple[GroupUsageMetric, ast.Expr]],
        date_to: datetime,
    ) -> list[UsageMetric]:
        date_from = date_to - timedelta(days=interval)
        prev_date_from = date_to - 2 * timedelta(days=interval)

        rows_by_day: dict[date, list] = {}
        if response.results:
            for row in response.results:
                day = row[0]
                if isinstance(day, datetime):
                    day = day.date()
                rows_by_day[day] = list(row[1:])

        num_metric_cols = len(group) * 2
        current_dates = self._date_range(date_from.date(), date_to.date())
        previous_dates = self._date_range(prev_date_from.date(), (date_from - timedelta(seconds=1)).date())

        results: list[UsageMetric] = []
        for i, (metric, _filter_expr) in enumerate(group):
            value_col = i * 2
            prev_col = i * 2 + 1

            zero_row = [0.0] * num_metric_cols
            current_daily = [float(rows_by_day.get(d, zero_row)[value_col]) for d in current_dates]
            previous_daily = [float(rows_by_day.get(d, zero_row)[prev_col]) for d in previous_dates]

            total_value = sum(current_daily)
            total_previous = sum(previous_daily)
            change_pct = ((total_value - total_previous) / total_previous * 100) if total_previous > 0 else None

            is_sparkline = metric.display == GroupUsageMetric.Display.SPARKLINE

            results.append(
                UsageMetric(
                    id=str(metric.id),
                    name=metric.name,
                    format=metric.format,
                    display=metric.display,
                    interval=metric.interval,
                    value=total_value,
                    previous=total_previous,
                    change_from_previous_pct=change_pct,
                    timeseries=current_daily if is_sparkline else None,
                    timeseries_labels=[d.isoformat() for d in current_dates] if is_sparkline else None,
                )
            )

        return results

    @staticmethod
    def _date_range(start: date, end: date) -> list[date]:
        num_days = (end - start).days + 1
        return [start + timedelta(days=i) for i in range(max(0, num_days))]

    def _get_entity_filter(self) -> ast.CompareOperation:
        if self._is_group_query:
            return ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[f"$group_{self.query.group_type_index}"]),
                right=ast.Constant(value=self.query.group_key),
            )

        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["person_id"]),
            right=ast.Constant(value=self.query.person_id),
        )

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        metric_fingerprints = sorted(
            (str(m.id), m.display, m.math, m.math_property or "", str(m.filters), str(m.interval))
            for m in self._usage_metrics
        )
        payload["usage_metric_fingerprints"] = metric_fingerprints
        return payload
