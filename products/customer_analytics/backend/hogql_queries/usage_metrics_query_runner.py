from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from posthog.schema import CachedUsageMetricsQueryResponse, UsageMetric, UsageMetricsQuery, UsageMetricsQueryResponse

from posthog.hogql import ast
from posthog.hogql.database.models import UnknownDatabaseField
from posthog.hogql.parser import parse_select

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

        with self.timings.measure("usage_metrics_query_hogql_execute"):
            response = execute_hogql_query(
                query_type="usage_metrics_query",
                query=self.to_query(),
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
            )

        with self.timings.measure("post_processing_query_results"):
            if not response.columns or not response.results:
                # Check is here so that mypy is happy
                results = []
            else:
                results = [UsageMetric.model_validate(dict(zip(response.columns, row))) for row in response.results]
            results.sort(key=lambda x: x.name, reverse=True)

        return UsageMetricsQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        metric_queries: list[ast.SelectQuery | ast.SelectSetQuery] = [
            query for metric in self._get_usage_metrics() if (query := self._get_metric_query(metric)) is not None
        ]

        if not metric_queries:
            columns = ["id", "name", "format", "display", "interval", "value", "previous", "change_from_previous_pct"]
            return ast.SelectQuery.empty(columns={key: UnknownDatabaseField(name=key) for key in columns})

        return ast.SelectSetQuery.create_from_queries(queries=metric_queries, set_operator="UNION ALL")

    def _get_usage_metrics(self) -> list[GroupUsageMetric]:
        """
        Fetch all metrics for the team, regardless of group_type_index.
        The model conception was too coupled to groups, we'll need to make it group-agnostic to support person-level
        metrics. For now, as a PoC, will simply ignore group_type_index.

        """
        with self.timings.measure("get_usage_metrics"):
            return list(
                GroupUsageMetric.objects.filter(team=self.team).only("name", "format", "interval", "display", "filters")
            )

    def _get_metric_query(self, metric: GroupUsageMetric) -> ast.SelectQuery | ast.SelectSetQuery | None:
        with self.timings.measure("get_metric_query"):
            filter_expr = metric.get_expr()
            if filter_expr == ast.Constant(value=True):
                return None

            where_expr = ast.And(exprs=[self._get_entity_filter(), *self._get_date_filter(metric=metric), filter_expr])
            date_to = datetime.now(tz=ZoneInfo("UTC"))
            date_from = date_to - timedelta(days=metric.interval)
            prev_date_from = date_to - 2 * timedelta(days=metric.interval)

        return parse_select(
            """
            SELECT
                *,
                if(previous > 0, ((value - previous) / previous) * 100, NULL) as change_from_previous_pct
            FROM (
                SELECT
                    {id} as id,
                    {name} as name,
                    {format} as format,
                    {display} as display,
                    {interval} as interval,
                    countIf(timestamp >= {date_from} AND timestamp <= {date_to}) as value,
                    countIf(timestamp >= {prev_date_from} AND timestamp < {date_from}) as previous
                FROM events
                WHERE {where_expr}
            )
        """,
            placeholders={
                "id": ast.Constant(value=str(metric.id)),
                "name": ast.Constant(value=metric.name),
                "format": ast.Constant(value=metric.format),
                "display": ast.Constant(value=metric.display),
                "interval": ast.Constant(value=metric.interval),
                "where_expr": where_expr,
                "date_from": ast.Constant(value=date_from),
                "prev_date_from": ast.Constant(value=prev_date_from),
                "date_to": ast.Constant(value=date_to),
            },
        )

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

    def _get_date_filter(self, metric: GroupUsageMetric) -> list[ast.CompareOperation]:
        date_to = datetime.now(tz=ZoneInfo("UTC"))
        date_from = date_to - 2 * timedelta(days=metric.interval)

        return [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=date_from),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=date_to),
            ),
        ]
