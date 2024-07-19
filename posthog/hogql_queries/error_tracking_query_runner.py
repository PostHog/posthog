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
            offset=self.query.offset if self.query.offset else None,
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
            ast.Alias(alias="last_seen", expr=ast.Call(name="max", args=[ast.Field(chain=["timestamp"])])),
            ast.Alias(alias="first_seen", expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])])),
            ast.Alias(alias="error", expr=ast.Call(name="any", args=[ast.Field(chain=["properties"])])),
        ]

        # "any(properties) as error",

        if self.query.fingerprint:
            # Include the event data when looking at an individual fingerprint
            exprs.append(
                ast.Alias(
                    alias="events",
                    expr=ast.Call(
                        name="groupArray",
                        args=[
                            ast.Call(
                                name="tuple",
                                args=[
                                    ast.Field(chain=["uuid"]),
                                    ast.Field(chain=["properties"]),
                                    ast.Field(chain=["timestamp"]),
                                ],
                            )
                        ],
                    ),
                )
            )
        else:
            exprs.append(self.fingerprint_grouping_expr)

        exprs.extend([parse_expr(x) for x in self.query.select])

        return exprs

    @property
    def fingerprint_grouping_expr(self):
        groups = self.error_tracking_groups.values()

        expr: ast.Expr = ast.Field(chain=["properties", "$exception_fingerprint"])

        if groups:
            args: list[ast.Expr] = []
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
            expr = ast.Call(
                name="multiIf",
                args=args,
            )

        return ast.Alias(
            alias="fingerprint",
            expr=expr,
        )

    def where(self):
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value="$exception"),
            ),
            ast.Placeholder(field="filters"),
        ]

        if self.query.fingerprint:
            group = self.group_or_default(self.query.fingerprint)
            exprs.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["properties", "$exception_fingerprint"]),
                    right=ast.Constant(value=[group["fingerprint"], *group["merged_fingerprints"]]),
                    op=ast.CompareOperationOp.In,
                ),
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

    def results(self, columns, query_results):
        mapped_results = [dict(zip(columns, value)) for value in query_results]
        results = []
        for result_dict in mapped_results:
            fingerprint = self.query.fingerprint if self.query.fingerprint else result_dict["fingerprint"]
            group = self.group_or_default(fingerprint)
            events: list = []
            if "events" in result_dict:
                events = [
                    {"uuid": str(e[0]), "properties": e[1], "timestamp": e[2]} for e in result_dict.get("events", [])
                ]
            results.append(group | result_dict | {"events": events})
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

    def where_exprs(self):
        return []

    def group_or_default(self, fingerprint):
        return self.error_tracking_groups.get(
            fingerprint,
            {
                "fingerprint": fingerprint,
                "assignee": None,
                "merged_fingerprints": [],
                "status": str(ErrorTrackingGroup.Status.ACTIVE),
            },
        )

    @cached_property
    def error_tracking_groups(self):
        queryset = ErrorTrackingGroup.objects.prefetch_related("assignee").filter(
            status__in=[ErrorTrackingGroup.Status.ACTIVE], team=self.team
        )
        queryset = queryset.filter(fingerprint=self.query.fingerprint) if self.query.fingerprint else queryset
        queryset = queryset.values("fingerprint", "merged_fingerprints", "status", "assignee")
        return {item["fingerprint"]: item for item in queryset}
