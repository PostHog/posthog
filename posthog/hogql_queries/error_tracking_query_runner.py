import re
import structlog

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
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.error_tracking import ErrorTrackingIssue

logger = structlog.get_logger(__name__)

INTERVAL_FUNCTIONS = {
    "minute": "toStartOfMinute",
    "hour": "toStartOfHour",
    "day": "toStartOfDay",
    "week": "toStartOfWeek",
    "month": "toStartOfMonth",
}


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
            offset=self.query.offset,
        )

    def to_query(self) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=self.select(),
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=self.where(),
            order_by=self.order_by,
            group_by=[ast.Field(chain=["issue_id"])],
        )

    def select(self):
        exprs: list[ast.Expr] = [
            ast.Alias(alias="id", expr=ast.Field(chain=["issue_id"])),
            ast.Alias(
                alias="occurrences", expr=ast.Call(name="count", distinct=True, args=[ast.Field(chain=["uuid"])])
            ),
            ast.Alias(
                alias="sessions", expr=ast.Call(name="count", distinct=True, args=[ast.Field(chain=["$session_id"])])
            ),
            ast.Alias(
                alias="users", expr=ast.Call(name="count", distinct=True, args=[ast.Field(chain=["distinct_id"])])
            ),
            ast.Alias(alias="last_seen", expr=ast.Call(name="max", args=[ast.Field(chain=["timestamp"])])),
            ast.Alias(alias="first_seen", expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])])),
            ast.Alias(alias="volumeDay", expr=self.volume(24, "hour", 0)),
            ast.Alias(alias="volumeMonth", expr=self.volume(31, "day", 0)),
        ]

        if self.query.customVolume:
            value = self.query.customVolume.get("value")
            offset = self.query.customVolume.get("offset")
            interval = self.query.customVolume.get("interval")
            exprs.append(
                ast.Alias(
                    alias="customVolume",
                    expr=self.volume(value, interval, offset),
                )
            )

        if self.query.issueId:
            exprs.append(
                ast.Alias(
                    alias="earliest",
                    expr=ast.Call(
                        name="argMin", args=[ast.Field(chain=["properties"]), ast.Field(chain=["timestamp"])]
                    ),
                )
            )

        return exprs

    def where(self):
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value="$exception"),
            ),
            ast.Call(
                name="isNotNull",
                args=[ast.Field(chain=["issue_id"])],
            ),
            ast.Placeholder(expr=ast.Field(chain=["filters"])),
        ]

        if self.query.issueId:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["issue_id"]),
                    right=ast.Constant(value=self.query.issueId),
                )
            )

        if self.query.searchQuery:
            # TODO: Refine this so it only searches the frames inside $exception_list
            # TODO: We'd eventually need a more efficient searching strategy
            # TODO: Add fuzzy search support

            # first parse the search query to split it into words, except for quoted strings
            # then search for each word in the exception properties
            tokens = search_tokenizer(self.query.searchQuery)
            and_exprs: list[ast.Expr] = []

            if len(tokens) > 10:
                raise ValueError("Too many search tokens")

            for token in tokens:
                if not token:
                    continue

                or_exprs: list[ast.Expr] = []

                props_to_search = [
                    "$exception_list",
                    "$exception_type",
                    "$exception_message",
                ]
                for prop in props_to_search:
                    or_exprs.append(
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Gt,
                            left=ast.Call(
                                name="position",
                                args=[
                                    ast.Call(name="lower", args=[ast.Field(chain=["properties", prop])]),
                                    ast.Call(name="lower", args=[ast.Constant(value=token)]),
                                ],
                            ),
                            right=ast.Constant(value=0),
                        )
                    )

                and_exprs.append(
                    ast.Or(
                        exprs=or_exprs,
                    )
                )
            exprs.append(ast.And(exprs=and_exprs))

        return ast.And(exprs=exprs)

    def calculate(self):
        with self.timings.measure("error_tracking_query_hogql_execute"):
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
        results = []
        mapped_results = [dict(zip(columns, value)) for value in query_results]

        issue_ids = [result["id"] for result in mapped_results]

        with self.timings.measure("issue_fetching_execute"):
            issues = self.error_tracking_issues(issue_ids)

        with self.timings.measure("issue_resolution"):
            for result_dict in mapped_results:
                issue = issues.get(result_dict["id"])
                if issue:
                    results.append(
                        issue | result_dict | {"assignee": self.query.assignee, "id": str(result_dict["id"])}
                    )
                else:
                    logger.error(
                        "error tracking issue not found",
                        issue_id=result_dict["id"],
                        exc_info=True,
                    )

        return results

    def volume(self, value, interval, offset):
        toStartOfInterval = INTERVAL_FUNCTIONS.get(interval)
        return parse_expr(
            f"reverse(arrayMap(x -> countEqual(groupArray(dateDiff('{interval}', {toStartOfInterval}(timestamp), {toStartOfInterval}(subtractHours(now(), {offset})))), x), range({value})))"
        )

    @property
    def order_by(self):
        return (
            [
                ast.OrderExpr(
                    expr=ast.Field(chain=[self.query.orderBy]),
                    order="ASC" if self.query.orderBy == "first_seen" else "DESC",
                )
            ]
            if self.query.orderBy
            else None
        )

    @cached_property
    def properties(self):
        return self.query.filterGroup.values[0].values if self.query.filterGroup else None

    def error_tracking_issues(self, ids):
        queryset = ErrorTrackingIssue.objects.filter(team=self.team, id__in=ids)
        queryset = (
            queryset.filter(id=self.query.issueId)
            if self.query.issueId
            else queryset.filter(status__in=[ErrorTrackingIssue.Status.ACTIVE])
        )
        queryset = (
            queryset.filter(errortrackingissueassignment__user_id=self.query.assignee)
            if self.query.assignee
            else queryset
        )
        issues = queryset.values("id", "status", "name", "description")
        return {item["id"]: item for item in issues}


def search_tokenizer(query: str) -> list[str]:
    # parse the search query to split it into words, except for quoted strings. Strip quotes from quoted strings.
    # Example: 'This is a "quoted string" and this is \'another one\' with some words'
    # Output: ['This', 'is', 'a', 'quoted string', 'and', 'this', 'is', 'another one', 'with', 'some', 'words']
    # This doesn't handle nested quotes, and some complex edge cases, but we don't really need that for now.
    # If requirements do change, consider using a proper parser like `pyparsing`
    pattern = r'"[^"]*"|\'[^\']*\'|\S+'
    tokens = re.findall(pattern, query)
    return [token.strip("'\"") for token in tokens]
