from abc import abstractmethod
from typing import Any, Generic, Optional, TypeVar, Union, cast, TypeGuard

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    HogQLFilters,
    ErrorTrackingQuery,
    ErrorTrackingQueryResponse,
    CachedErrorTrackingQueryResponse,
    ErrorTrackingGroupQuery,
    ErrorTrackingGroupQueryResponse,
    CachedErrorTrackingGroupQueryResponse,
)
from posthog.hogql.parser import parse_expr
from posthog.models.error_tracking import ErrorTrackingGroup
from posthog.models.filters.mixins.utils import cached_property

# Q = TypeVar("Q", bound=BaseModel)


class BaseErrorTrackingRunner(QueryRunner):
    query: ErrorTrackingQuery | ErrorTrackingGroupQuery
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset if self.query.offset else None,
        )

    def to_query(self) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=self._select(),
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=self._where(),
            order_by=self.order_by,
            group_by=self._group_by(),
        )

    def _select(self):
        default_exprs: list[ast.Expr] = self.default_select_exprs
        parsed_exprs = [parse_expr(x) for x in self.query.select]
        return [*default_exprs, *parsed_exprs]

    def _where(self):
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value="$pageview"),
            ),
            ast.Placeholder(field="filters"),
        ]
        exprs.extend(self.where_exprs)
        return ast.And(exprs=exprs)

    def _group_by(self):
        return None

    def calculate(self):
        query_result = self.paginator.execute_hogql_query(
            query=self.to_query(),
            team=self.team,
            query_type="ErrorTrackingQuery",
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            filters=HogQLFilters(
                dateRange=self.query.dateRange,
                filterTestAccounts=self.query.filterTestAccounts,
                properties=self.properties,
            ),
        )

        columns: list[str] = query_result.columns or []
        results = self.results(columns, query_result.results)

        return self.response(
            columns=columns,
            results=results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    @abstractmethod
    def calculate(self) -> R:
        raise NotImplementedError()

    @abstractmethod
    def default_columns(self) -> R:
        raise NotImplementedError()

    @property
    def order_by(self):
        return (
            [
                ast.OrderExpr(
                    expr=ast.Field(chain=[self.query.order]),
                    order="ASC" if self.query.order == "first_seen" else "DESC",
                )
            ]
            if self.query.order
            else None
        )

    @cached_property
    def properties(self):
        return self.query.filterGroup.values[0].values if self.query.filterGroup else None

    @property
    @abstractmethod
    def where_exprs(self):
        raise NotImplementedError()

    @property
    @abstractmethod
    def where_exprs(self):
        raise NotImplementedError()


class ErrorTrackingQueryRunner(BaseErrorTrackingRunner):
    query: ErrorTrackingQuery
    response: ErrorTrackingQueryResponse
    cached_response: CachedErrorTrackingQueryResponse
    where_exprs: []

    def default_select(self):
        args: list[ast.Expr] = []
        groups = self.error_tracking_groups.values()

        if not groups:
            return ast.Alias(
                alias="fingerprint",
                expr=ast.Field(chain=["properties", "$exception_fingerprint"]),
            ), ast.Field(chain=["events", "properties", "$exception_fingerprint"])

        for group in groups:
            # set the "fingerprint" of an exception to match that of the groups primary fingerprint
            # replaces exceptions in "merged_fingerprints" with the group fingerprint
            args.extend(
                [
                    ast.CompareOperation(
                        left=ast.Field(chain=["properties", "$exception_fingerprint"]),
                        right=ast.Constant(value=[group["fingerprint"], *group["merged_fingerprints"]]),
                        op=ast.CompareOperationOp.In,
                    ),
                    ast.Constant(value=group["fingerprint"]),
                ]
            )

        # default to $exception_fingerprint property for exception events that don't match a group
        args.append(ast.Field(chain=["properties", "$exception_fingerprint"]))

        return [ast.Alias(
            alias="fingerprint",
            expr=ast.Call(
                name="multiIf",
                args=args,
            ),
        )]

    def group_by(self):
        return [ast.Field(chain=["fingerprint"])]

    def results(self, columns, results):
        query_results = [dict(zip(columns, value)) for value in results]

        results = []
        for result in query_results:
            fingerprint = result["fingerprint"]
            group = self.error_tracking_groups.get(
                fingerprint,
                {
                    "fingerprint": fingerprint,
                    "assignee": None,
                    "merged_fingerprints": [],
                    "status": str(ErrorTrackingGroup.Status.ACTIVE),
                },
            )
            results.append(group | result)

        return results

    @cached_property
    def error_tracking_groups(self):
        queryset = (
            ErrorTrackingGroup.objects.prefetch_related("assignee")
            .filter(status__in=[ErrorTrackingGroup.Status.ACTIVE], team=self.team)
            .values("fingerprint", "merged_fingerprints", "status", "assignee")
        )
        return {item["fingerprint"]: item for item in queryset}



class ErrorTrackingGroupQueryRunner(BaseErrorTrackingRunner)
    query: ErrorTrackingGroupQuery
    response: ErrorTrackingGroupQueryResponse
    cached_response: CachedErrorTrackingGroupQueryResponse
    where_exprs: [ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=["properties", "$exception_fingerprint"]),
        right=ast.Constant(value=self.query.fingerprint),
    )]
