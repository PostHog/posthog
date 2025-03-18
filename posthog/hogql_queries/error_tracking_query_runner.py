import re
import structlog
from typing import Any

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    HogQLFilters,
    ErrorTrackingQuery,
    ErrorTrackingSparklineConfig,
    ErrorTrackingQueryResponse,
    CachedErrorTrackingQueryResponse,
    Interval,
)
from posthog.hogql.parser import parse_expr, parse_select
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
    sparklineConfigs: dict[str, ErrorTrackingSparklineConfig]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )

        self.sparklineConfigs = {
            "volumeDay": ErrorTrackingSparklineConfig(interval=Interval.HOUR, value=24),
            "volumeMonth": ErrorTrackingSparklineConfig(interval=Interval.DAY, value=31),
        }

        if self.query.customVolume:
            self.sparklineConfigs["customVolume"] = self.query.customVolume

    def to_query(self) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=self.select(),
            select_from=self.from_expr(),
            where=self.where(),
            order_by=self.order_by,
            group_by=[ast.Field(chain=["issue_id"])],
        )

    def from_expr(self):
        # for the second iteration of this query, we just need to select from the events table
        return parse_select("SELECT 1 FROM events").select_from  # type: ignore

    def select(self):
        # First, the easy groups - distinct uuid as occurrances, etc
        exprs: list[ast.Expr] = [
            ast.Alias(alias="id", expr=ast.Field(chain=["issue_id"])),
            ast.Alias(
                alias="occurrences", expr=ast.Call(name="count", distinct=True, args=[ast.Field(chain=["uuid"])])
            ),
            ast.Alias(
                alias="sessions",
                expr=ast.Call(
                    name="count",
                    distinct=True,
                    # the $session_id property can be blank if not set
                    # we do not want that case counted so cast it to `null` which is excluded by default
                    args=[
                        ast.Call(
                            name="nullIf",
                            args=[ast.Field(chain=["$session_id"]), ast.Constant(value="")],
                        )
                    ],
                ),
            ),
            ast.Alias(
                alias="users", expr=ast.Call(name="count", distinct=True, args=[ast.Field(chain=["distinct_id"])])
            ),
            ast.Alias(alias="last_seen", expr=ast.Call(name="max", args=[ast.Field(chain=["timestamp"])])),
            ast.Alias(alias="first_seen", expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])])),
        ]

        for alias, config in self.sparklineConfigs.items():
            exprs.append(ast.Alias(alias=alias, expr=self.select_sparkline_array(alias, config)))

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

    def select_sparkline_array(self, alias: str, config: ErrorTrackingSparklineConfig):
        toStartOfInterval = INTERVAL_FUNCTIONS.get(config.interval)
        intervalStr = config.interval.value
        isHotIndex = f"dateDiff('{intervalStr}', {toStartOfInterval}(timestamp), {toStartOfInterval}(now())) = x"
        isLiveIndexFn = f"if({isHotIndex}, 1, 0)"

        constructed = f"arrayMap(x -> {isLiveIndexFn}, range({config.value}))"
        summed = f"reverse(sumForEach({constructed}))"
        return parse_expr(summed)

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

                and_exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Gt,
                        left=ast.Call(
                            name="position",
                            args=[
                                ast.Call(name="lower", args=[ast.Field(chain=["properties", "$exception_list"])]),
                                ast.Call(name="lower", args=[ast.Constant(value=token)]),
                            ],
                        ),
                        right=ast.Constant(value=0),
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
                        issue
                        | {
                            ## First seen timestamp is bounded by date range when querying for the list (comes from clickhouse) but it is global when querying for a single issue
                            "first_seen": (
                                issue.get("first_seen") if self.query.issueId else result_dict.get("first_seen")
                            ),
                            "last_seen": result_dict.get("last_seen"),
                            "earliest": result_dict.get("earliest") if self.query.issueId else None,
                            "aggregations": self.extract_aggregations(result_dict),
                        }
                    )

        return results

    def extract_aggregations(self, result):
        aggregations = {f: result[f] for f in ("occurrences", "sessions", "users", "volumeDay", "volumeMonth")}
        aggregations["customVolume"] = result.get("customVolume") if "customVolume" in result else None
        return aggregations

    @property
    def order_by(self):
        return (
            [
                ast.OrderExpr(
                    expr=ast.Field(chain=[self.query.orderBy]),
                    order=(
                        self.query.orderDirection.value
                        if self.query.orderDirection
                        else "ASC"
                        if self.query.orderBy == "first_seen"
                        else "DESC"
                    ),
                )
            ]
            if self.query.orderBy
            else None
        )

    @cached_property
    def properties(self):
        return self.query.filterGroup.values[0].values if self.query.filterGroup else None

    def error_tracking_issues(self, ids):
        status = self.query.status
        queryset = (
            ErrorTrackingIssue.objects.with_first_seen().select_related("assignment").filter(team=self.team, id__in=ids)
        )

        if self.query.issueId:
            queryset = queryset.filter(id=self.query.issueId)
        elif status and not status == "all":
            queryset = queryset.filter(status=status)

        if self.query.assignee:
            queryset = (
                queryset.filter(assignment__user_id=self.query.assignee.id)
                if self.query.assignee.type == "user"
                else queryset.filter(assignment__user_group_id=self.query.assignee.id)
            )

        issues = queryset.values(
            "id", "status", "name", "description", "first_seen", "assignment__user_id", "assignment__user_group_id"
        )

        results = {}
        for issue in issues:
            result: dict[str, Any] = {
                "id": str(issue["id"]),
                "name": issue["name"],
                "status": issue["status"],
                "description": issue["description"],
                "first_seen": issue["first_seen"],
                "assignee": None,
            }

            assignment_user_id = issue.get("assignment__user_id")
            assignment_user_group_id = issue.get("assignment__user_group_id")

            if assignment_user_id or assignment_user_group_id:
                result["assignee"] = {
                    "id": assignment_user_id or str(assignment_user_group_id),
                    "type": "user" if assignment_user_id else "user_group",
                }

            results[issue["id"]] = result

        return results


def search_tokenizer(query: str) -> list[str]:
    # parse the search query to split it into words, except for quoted strings. Strip quotes from quoted strings.
    # Example: 'This is a "quoted string" and this is \'another one\' with some words'
    # Output: ['This', 'is', 'a', 'quoted string', 'and', 'this', 'is', 'another one', 'with', 'some', 'words']
    # This doesn't handle nested quotes, and some complex edge cases, but we don't really need that for now.
    # If requirements do change, consider using a proper parser like `pyparsing`
    pattern = r'"[^"]*"|\'[^\']*\'|\S+'
    tokens = re.findall(pattern, query)
    return [token.strip("'\"") for token in tokens]
