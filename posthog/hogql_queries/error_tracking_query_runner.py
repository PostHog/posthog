from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    HogQLFilters,
    ErrorTrackingQuery,
    ErrorTrackingQueryResponse,
    CachedErrorTrackingQueryResponse,
)
from posthog.hogql.parser import parse_expr
from posthog.models.error_tracking import ErrorTrackingGroup
from posthog.models.filters.mixins.utils import cached_property


class ErrorTrackingQueryRunner(QueryRunner):
    query: ErrorTrackingQuery
    response: ErrorTrackingQueryResponse
    paginator: HogQLHasMorePaginator
    cached_response: CachedErrorTrackingQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset if self.query.offset else None,
        )

    def to_query(self) -> ast.SelectQuery:
        parsed_select = [parse_expr(x) for x in self.query.select]
        return ast.SelectQuery(
            select=[self.primary_fingerprint_alias(), *parsed_select],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=self._where(),
            order_by=self._order_by(),
            # group_by=[ast.Field(chain=["events", "properties", "$exception_fingerprint"])],
            group_by=[ast.Field(chain=["primary_fingerprint"])],
        )

    def primary_fingerprint_alias(self):
        args: list[ast.Expr] = []
        for group in self.error_tracking_groups:
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

        args.append(ast.Field(chain=["properties", "$exception_fingerprint"]))

        return ast.Alias(
            alias="primary_fingerprint",
            expr=ast.Call(
                name="multiIf",
                args=args,
            ),
        )

    def _where(self):
        where_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value="$exception"),
            ),
            ast.Placeholder(field="filters"),
        ]

        if self.query.fingerprint:
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["properties", "$exception_fingerprint"]),
                    right=ast.Constant(value=self.query.fingerprint),
                )
            )

        return ast.And(exprs=where_exprs)

    def _order_by(self):
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

    def calculate(self):
        properties = self.query.filterGroup.values[0].values if self.query.filterGroup else None

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
                properties=properties,
            ),
        )

        results = []
        for _, query_result in enumerate(query_result.results):
            group = next(
                (x for x in self.error_tracking_groups if x["fingerprint"] == query_result[0]),
                {
                    "fingerprint": query_result[0],
                    "assignee": None,
                    "merged_fingerprints": [],
                    "status": ErrorTrackingGroup.Status.ACTIVE,
                },
            )
            result = {}

            result.ex
            result.append(*group) if group is not None else None
            results.append(result)

        print(results)

        return ErrorTrackingQueryResponse(
            columns=query_result.columns,
            results=query_result.results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    @cached_property
    def error_tracking_groups(self):
        return (
            ErrorTrackingGroup.objects.prefetch_related("assignee")
            .filter(status__in=[ErrorTrackingGroup.Status.ACTIVE], team=self.team)
            .values("fingerprint", "merged_fingerprints", "status", "assignee")
        )
