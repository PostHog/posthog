from datetime import date
from functools import cached_property
from typing import Generic
from uuid import UUID

from posthog.schema import (
    AccountActivityMatrixColumn,
    AccountActivityMatrixQuery,
    BookActivityFirstsQuery,
    BookActivityMatrixQuery,
    BookActivityPeopleQuery,
    HogQLQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.query_runner import AR, AnalyticsQueryRunner
from posthog.week_start_day import WeekStartDay

DEFAULT_ROW_LIMIT = 50
MAX_ROW_LIMIT = 200


class ActivityQueryRunner(AnalyticsQueryRunner[AR], Generic[AR]):
    query: AccountActivityMatrixQuery | BookActivityMatrixQuery | BookActivityPeopleQuery | BookActivityFirstsQuery

    @cached_property
    def _row_limit(self) -> int:
        return max(1, min(self.query.rowLimit or DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT))

    @cached_property
    def _week_start_day(self) -> WeekStartDay:
        return WeekStartDay(self.team.week_start_day or WeekStartDay.SUNDAY)

    def _execute(self, query_type: str, query: ast.SelectQuery) -> HogQLQueryResponse:
        tag_queries(product=Product.CUSTOMER_ANALYTICS, feature=Feature.QUERY)
        return execute_hogql_query(
            query_type=query_type,
            query=query,
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            workload=Workload.ONLINE,
        )


def activity_columns(buckets: list[date], current: date) -> list[AccountActivityMatrixColumn]:
    return [AccountActivityMatrixColumn(key=bucket.isoformat(), partial=bucket == current) for bucket in buckets]


def is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
