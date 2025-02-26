import re
import structlog
from typing import Any

from posthog.hogql import ast
from posthog.hogql.base import CTE
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
    sparkLineConfigs: dict[str, ErrorTrackingSparklineConfig]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )

        self.sparkLineConfigs = {
            "volumeDay": ErrorTrackingSparklineConfig(interval=Interval.HOUR, value=24),
            "volumeMonth": ErrorTrackingSparklineConfig(interval=Interval.DAY, value=31),
        }

        if self.query.customVolume:
            self.sparkLineConfigs["customVolume"] = self.query.customVolume

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

        for alias, config in self.sparkLineConfigs.items():
            exprs.append(ast.Alias(alias=alias, expr=self.select_sparkline_array(alias, config)))

        if self.query.issueId:
            exprs.append(ast.Alias(alias="earliest", expr=parse_expr("summary.earliest")))

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
                        issue
                        | {
                            "first_seen": result_dict.get("first_seen"),
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

    def sparkline_volume(self, alias: str, value: int):
        # We coalesce here because our sparklines are time constrained to only the last day, month, or whatever, and
        # if we're returning whose last event was before then, its sparkline volume will be null
        default = f"arrayMap(x -> 0, range({value}))"
        coalesced = f"coalesce(cte_{alias}.count, {default})"
        expr = f"if(greater(length({coalesced}), 0), {coalesced}, {default})"
        return parse_expr(expr)

    # We use CTEs to calculate the volume for sparklines
    def sparkline_ctes(self):
        ctes: dict[str, CTE] = {}

        for alias, config in self.sparkLineConfigs.items():
            subquery = self.sparkline_cte_select(config)
            ctes[f"cte_{alias}"] = ast.CTE(name=f"cte_{alias}", expr=subquery, cte_type="subquery")

        return ctes

    def sparkline_cte_select(self, config: ErrorTrackingSparklineConfig):
        toStartOfInterval = INTERVAL_FUNCTIONS.get(config.interval)
        intervalStr = config.interval.value

        tsLimit = ast.CompareOperation(
            op=ast.CompareOperationOp.Gt,
            left=ast.Field(chain=["timestamp"]),
            right=parse_expr(f"now() - interval {config.value + 1} {intervalStr}"),
        )

        where = self.where()
        where.exprs.append(tsLimit)

        samples = CTE(
            name="d", expr=parse_expr(f"(SELECT arrayJoin(range({config.value})) AS diff)"), cte_type="subquery"
        )

        distinct_issues_select = ast.SelectQuery(
            select=[ast.Alias(alias="issue_id", expr=ast.Field(chain=["issue_id"]))],
            distinct=True,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=where,
        )
        distinct_issues = CTE(name="di", expr=distinct_issues_select, cte_type="subquery")

        event_counts_select = ast.SelectQuery(
            select=[
                ast.Alias(alias="count", expr=ast.Call(name="count", args=[ast.Field(chain=["uuid"])])),
                parse_expr(
                    f"dateDiff('{intervalStr}', {toStartOfInterval}(timestamp), {toStartOfInterval}(now())) as diff"
                ),
                ast.Alias(alias="issue_id", expr=ast.Field(chain=["issue_id"])),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            group_by=[ast.Field(chain=["diff"]), ast.Field(chain=["issue_id"])],
            where=where,
            having=ast.CompareOperation(
                op=ast.CompareOperationOp.Lt, left=ast.Field(chain=["diff"]), right=ast.Constant(value=24)
            ),
        )

        event_counts = CTE(name="ec", expr=event_counts_select, cte_type="subquery")

        ctes = {"s": samples, "di": distinct_issues, "ec": event_counts}

        inner = ast.SelectQuery(
            ctes=ctes,
            select=[
                parse_expr("coalesce(ec.count, 0) as count"),
                parse_expr("s.diff as diff"),
                parse_expr("di.issue_id as issue_id"),
            ],
            # FROM s CROSS JOIN di LEFT JOIN ec ON s.diff = ec.diff AND di.issue_id = ec.issue_id
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["s"]),
                next_join=ast.JoinExpr(
                    join_type="CROSS JOIN",
                    table=ast.Field(chain=["di"]),
                    next_join=ast.JoinExpr(
                        join_type="LEFT JOIN",
                        table=ast.Field(chain=["ec"]),
                        constraint=ast.JoinConstraint(
                            constraint_type="ON",
                            expr=ast.And(
                                exprs=[
                                    ast.CompareOperation(
                                        left=ast.Field(chain=["s", "diff"]),
                                        right=ast.Field(chain=["ec", "diff"]),
                                        op=ast.CompareOperationOp.Eq,
                                    ),
                                    ast.CompareOperation(
                                        left=ast.Field(chain=["di", "issue_id"]),
                                        right=ast.Field(chain=["ec", "issue_id"]),
                                        op=ast.CompareOperationOp.Eq,
                                    ),
                                ]
                            ),
                        ),
                    ),
                ),
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["diff"]), order="DESC")],
        )

        inner_cte = CTE(name="inner", expr=inner, cte_type="subquery")

        outer = ast.SelectQuery(
            ctes={"inner": inner_cte},
            select=[parse_expr("inner.issue_id"), parse_expr("groupArray(inner.count) as count")],
            select_from=ast.JoinExpr(table=ast.Field(chain=["inner"])),
            group_by=[ast.Field(chain=["issue_id"])],
        )

        return outer

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
        status = self.query.status
        queryset = ErrorTrackingIssue.objects.select_related("assignment").filter(team=self.team, id__in=ids)

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
            "id", "status", "name", "description", "assignment__user_id", "assignment__user_group_id"
        )

        results = {}
        for issue in issues:
            result: dict[str, Any] = {
                "id": str(issue["id"]),
                "name": issue["name"],
                "status": issue["status"],
                "description": issue["description"],
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
