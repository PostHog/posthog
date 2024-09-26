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
    cached_response: CachedErrorTrackingQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
        )

    def to_query(self) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=self.select(),
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=self.where(),
            order_by=self.order_by,
            group_by=self.group_by(),
        )

    def select(self):
        exprs: list[ast.Expr] = [
            ast.Alias(alias="occurrences", expr=ast.Call(name="count", args=[])),
            ast.Alias(
                alias="sessions", expr=ast.Call(name="count", distinct=True, args=[ast.Field(chain=["$session_id"])])
            ),
            ast.Alias(
                alias="users", expr=ast.Call(name="count", distinct=True, args=[ast.Field(chain=["distinct_id"])])
            ),
            ast.Alias(alias="last_seen", expr=ast.Call(name="max", args=[ast.Field(chain=["timestamp"])])),
            ast.Alias(alias="first_seen", expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])])),
            ast.Alias(
                alias="description",
                expr=ast.Call(name="any", args=[ast.Field(chain=["properties", "$exception_message"])]),
            ),
            ast.Alias(
                alias="exception_type",
                expr=ast.Call(name="any", args=[ast.Field(chain=["properties", "$exception_type"])]),
            ),
        ]

        if not self.query.fingerprint:
            exprs.append(self.fingerprint_grouping_expr)

        if self.query.select:
            exprs.extend([parse_expr(x) for x in self.query.select])

        return exprs

    @property
    def fingerprint_grouping_expr(self):
        groups = self.error_tracking_groups.values()

        expr: ast.Expr = self.extracted_fingerprint_property()

        if groups:
            args: list[ast.Expr] = []
            for group in groups:
                # set the "fingerprint" of an exception to match that of the groups primary fingerprint
                # replaces exceptions in "merged_fingerprints" with the group fingerprint
                args.extend(
                    [
                        ast.Call(
                            name="has",
                            args=[
                                self.group_fingerprints([group]),
                                self.extracted_fingerprint_property(),
                            ],
                        ),
                        ast.Constant(value=group["fingerprint"]),
                    ]
                )

            # default to $exception_fingerprint property for exception events that don't match a group
            args.append(self.extracted_fingerprint_property())

            expr = ast.Call(
                name="multiIf",
                args=args,
            )

        return ast.Alias(alias="fingerprint", expr=expr)

    def where(self):
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value="$exception"),
            ),
            ast.Placeholder(chain=["filters"]),
        ]

        groups = []

        if self.query.fingerprint:
            groups.append(self.group_or_default(self.query.fingerprint))
        elif self.query.assignee:
            groups.extend(self.error_tracking_groups.values())

        if groups:
            exprs.append(
                ast.Call(
                    name="has",
                    args=[
                        self.group_fingerprints(groups),
                        self.extracted_fingerprint_property(),
                    ],
                ),
            )

        if self.query.searchQuery:
            # TODO: Refine this so it only searches the frames inside $exception_list
            props_to_search = ["$exception_list", "$exception_stack_trace_raw", "$exception_type", "$exception_message"]
            or_exprs: list[ast.Expr] = []
            for prop in props_to_search:
                or_exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Gt,
                        left=ast.Call(
                            name="position",
                            args=[
                                ast.Call(name="lower", args=[ast.Field(chain=["properties", prop])]),
                                ast.Call(name="lower", args=[ast.Constant(value=self.query.searchQuery)]),
                            ],
                        ),
                        right=ast.Constant(value=0),
                    )
                )

            if or_exprs:
                exprs.append(
                    ast.Or(
                        exprs=or_exprs,
                    )
                )

        return ast.And(exprs=exprs)

    def group_by(self):
        return None if self.query.fingerprint else [ast.Field(chain=["fingerprint"])]

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

        return ErrorTrackingQueryResponse(
            columns=columns,
            results=results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def results(self, columns: list[str], query_results: list):
        mapped_results = [dict(zip(columns, value)) for value in query_results]
        results = []
        for result_dict in mapped_results:
            fingerprint = self.query.fingerprint if self.query.fingerprint else result_dict["fingerprint"]
            group = self.group_or_default(fingerprint)
            results.append(result_dict | group)

        return results

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

    def group_or_default(self, fingerprint):
        return self.error_tracking_groups.get(
            str(fingerprint),
            {
                "fingerprint": fingerprint,
                "assignee": None,
                "merged_fingerprints": [],
                "status": str(ErrorTrackingGroup.Status.ACTIVE),
            },
        )

    def group_fingerprints(self, groups):
        exprs: list[ast.Expr] = []
        for group in groups:
            exprs.append(ast.Constant(value=group["fingerprint"]))
            for fp in group["merged_fingerprints"]:
                exprs.append(ast.Constant(value=fp))
        return ast.Array(exprs=exprs)

    def extracted_fingerprint_property(self):
        return ast.Call(
            name="JSONExtract",
            args=[
                ast.Call(
                    name="ifNull",
                    args=[
                        ast.Field(chain=["properties", "$exception_fingerprint"]),
                        ast.Constant(value="[]"),
                    ],
                ),
                ast.Constant(value="Array(String)"),
            ],
        )

    @cached_property
    def error_tracking_groups(self):
        queryset = ErrorTrackingGroup.objects.filter(team=self.team)
        queryset = (
            queryset.filter(fingerprint=self.query.fingerprint)
            if self.query.fingerprint
            else queryset.filter(status__in=[ErrorTrackingGroup.Status.ACTIVE])
        )
        queryset = queryset.filter(assignee=self.query.assignee) if self.query.assignee else queryset
        groups = queryset.values("fingerprint", "merged_fingerprints", "status", "assignee")
        return {str(item["fingerprint"]): item for item in groups}
