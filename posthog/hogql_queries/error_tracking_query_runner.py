from dataclasses import dataclass
import re
import structlog
from typing import Any
from django.core.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    HogQLFilters,
    ErrorTrackingQuery,
    ErrorTrackingQueryResponse,
    CachedErrorTrackingQueryResponse,
    DateRange,
)
from posthog.hogql.parser import parse_select
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.error_tracking import ErrorTrackingIssue
from posthog.models.property.util import property_to_django_filter

logger = structlog.get_logger(__name__)


@dataclass
class VolumeOptions:
    date_range: DateRange
    resolution: int


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

        if self.query.withAggregations is None:
            self.query.withAggregations = True

        if self.query.withFirstEvent is None:
            self.query.withFirstEvent = True

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
            ast.Alias(alias="last_seen", expr=ast.Call(name="max", args=[ast.Field(chain=["timestamp"])])),
            ast.Alias(alias="first_seen", expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])])),
        ]

        if self.query.withAggregations:
            volume_option = VolumeOptions(date_range=self.query.dateRange, resolution=self.query.volumeResolution)
            exprs.extend(
                [
                    ast.Alias(
                        alias="occurrences",
                        expr=ast.Call(name="count", distinct=True, args=[ast.Field(chain=["uuid"])]),
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
                        alias="users",
                        expr=ast.Call(name="count", distinct=True, args=[ast.Field(chain=["distinct_id"])]),
                    ),
                    ast.Alias(alias="volumeRange", expr=self.select_sparkline_array(volume_option)),
                ]
            )

        if self.query.withFirstEvent:
            exprs.append(
                ast.Alias(
                    alias="first_event",
                    expr=ast.Call(
                        name="argMin",
                        args=[
                            ast.Tuple(
                                exprs=[
                                    ast.Field(chain=["uuid"]),
                                    ast.Field(chain=["timestamp"]),
                                    ast.Field(chain=["properties"]),
                                ]
                            ),
                            ast.Field(chain=["timestamp"]),
                        ],
                    ),
                )
            )

        exprs.append(
            ast.Alias(
                alias="library",
                expr=ast.Call(
                    name="argMax", args=[ast.Field(chain=["properties", "$lib"]), ast.Field(chain=["timestamp"])]
                ),
            )
        )

        return exprs

    def select_sparkline_array(self, opts: VolumeOptions):
        """
        This function partitions a given time range into segments (or "buckets") based on the specified resolution and then computes the number of events occurring in each segment.
        The resolution determines the total number of segments in the time range.
        Accordingly, the duration of each segment is dictated by the total time range and the resolution.

        The equivalent SQL would look like:
            WITH
                toDateTime('2025-03-01 00:00:00') AS date_from,
                toDateTime('2025-03-20 00:00:00') AS date_to,
                10 AS resolution,
            SELECT
                sumForEach(
                    arrayMap(
                        bin ->
                            IF(
                                timestamp > bin AND dateDiff('seconds', bin, timestamp) < dateDiff('seconds', date_from, date_to) / resolution,
                                1,
                                0
                            ), ## If we are inside the right bucket, return 1, otherwise 0
                        arrayMap(
                            i -> dateAdd(
                                start_time,
                                toIntervalSecond(i * dateDiff('seconds', date_from, date_to) / resolution)
                            ),
                            range(0, resolution)
                        ) ## Generate an array of len resolution containing the start times of each segment
                    )
                ) AS counts
        """
        start_time = ast.Call(
            name="toDateTime",
            args=[
                ast.Constant(value=opts.date_range.date_from),
            ],
        )
        end_time = ast.Call(
            name="toDateTime",
            args=[
                ast.Constant(value=opts.date_range.date_to),
            ],
        )
        total_size = ast.Call(
            name="dateDiff",
            args=[
                ast.Constant(value="seconds"),
                start_time,
                end_time,
            ],
        )
        bin_size = ast.ArithmeticOperation(
            op=ast.ArithmeticOperationOp.Div,
            left=total_size,
            right=ast.Constant(value=opts.resolution),
        )
        bin_timestamps = ast.Call(
            name="arrayMap",
            args=[
                ast.Lambda(
                    args=["i"],
                    expr=ast.Call(
                        name="dateAdd",
                        args=[
                            start_time,
                            ast.Call(
                                name="toIntervalSecond",
                                args=[
                                    ast.ArithmeticOperation(
                                        op=ast.ArithmeticOperationOp.Mult, left=ast.Field(chain=["i"]), right=bin_size
                                    )
                                ],
                            ),
                        ],
                    ),
                ),
                ast.Call(
                    name="range",
                    args=[
                        ast.Constant(value=0),
                        ast.Constant(value=opts.resolution),
                    ],
                ),
            ],
        )
        hot_indices = ast.Call(
            name="arrayMap",
            args=[
                ast.Lambda(
                    args=["bin"],
                    expr=ast.Call(
                        name="if",
                        args=[
                            ast.And(
                                exprs=[
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.Gt,
                                        left=ast.Field(chain=["timestamp"]),
                                        right=ast.Field(chain=["bin"]),
                                    ),
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.LtEq,
                                        left=ast.Call(
                                            name="dateDiff",
                                            args=[
                                                ast.Constant(value="seconds"),
                                                ast.Field(chain=["bin"]),
                                                ast.Field(chain=["timestamp"]),
                                            ],
                                        ),
                                        right=bin_size,
                                    ),
                                ]
                            ),
                            ast.Constant(value=1),
                            ast.Constant(value=0),
                        ],
                    ),
                ),
                bin_timestamps,
            ],
        )
        summed = ast.Call(
            name="sumForEach",
            args=[hot_indices],
        )
        return summed

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

        if self.query.dateRange.date_from:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Call(
                        name="toDateTime",
                        args=[ast.Constant(value=self.query.dateRange.date_from)],
                    ),
                )
            )

        if self.query.dateRange.date_to:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Call(
                        name="toDateTime",
                        args=[ast.Constant(value=self.query.dateRange.date_to)],
                    ),
                )
            )

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

            if len(tokens) > 100:
                raise ValidationError("Too many search tokens")

            for token in tokens:
                if not token:
                    continue

                or_exprs: list[ast.Expr] = []

                props_to_search = {
                    ("properties",): [
                        "$exception_types",
                        "$exception_values",
                        "$exception_sources",
                        "$exception_functions",
                        "email",
                    ],
                    ("person", "properties"): [
                        "email",
                    ],
                }
                for chain_prefix, properties in props_to_search.items():
                    for prop in properties:
                        or_exprs.append(
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Gt,
                                left=ast.Call(
                                    name="position",
                                    args=[
                                        ast.Call(name="lower", args=[ast.Field(chain=[*chain_prefix, prop])]),
                                        ast.Call(name="lower", args=[ast.Constant(value=token)]),
                                    ],
                                ),
                                right=ast.Constant(value=0),
                            )
                        )

                and_exprs.append(ast.Or(exprs=or_exprs))

            exprs.append(ast.And(exprs=and_exprs))

        # We do this prefetching of a list of "valid" issue id's based on issue properties that aren't in
        # CH, so that when we run the aggregation and LIMIT, we can filter out the invalid issue id's
        # This is a hack - it'll break down if the list of valid issue id's is too long, but we do it for now
        prefetched_ids = self.prefetch_issue_ids()
        if prefetched_ids:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["issue_id"]),
                    right=ast.Constant(value=prefetched_ids),
                )
            )

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
                    filterTestAccounts=self.query.filterTestAccounts,
                    properties=self.hogql_properties,
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
                            "last_seen": result_dict.get("last_seen"),
                            "library": result_dict.get("library"),
                            "first_event": (
                                self.extract_event(result_dict.get("first_event"))
                                if self.query.withFirstEvent
                                else None
                            ),
                            "aggregations": (
                                self.extract_aggregations(result_dict) if self.query.withAggregations else None
                            ),
                        }
                    )

        return results

    def extract_event(self, event_tuple):
        if event_tuple is None:
            return None
        else:
            return {
                "uuid": str(event_tuple[0]),
                "timestamp": str(event_tuple[1]),
                "properties": event_tuple[2],
            }

    def extract_aggregations(self, result):
        aggregations = {f: result[f] for f in ("occurrences", "sessions", "users", "volumeRange")}
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
                else queryset.filter(assignment__role_id=self.query.assignee.id)
            )

        for filter in self.issue_properties:
            queryset = property_to_django_filter(queryset, filter)

        issues = queryset.values(
            "id",
            "status",
            "name",
            "description",
            "first_seen",
            "assignment__user_id",
            "assignment__role_id",
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
            assignment_role_id = issue.get("assignment__role_id")

            if assignment_user_id or assignment_role_id:
                result["assignee"] = {
                    "id": assignment_user_id or str(assignment_role_id),
                    "type": ("user" if assignment_user_id else "role"),
                }

            results[issue["id"]] = result

        return results

    def prefetch_issue_ids(self) -> list[str]:
        # We hit postgres to get a list of "valid" issue id's based on issue properties that aren't in
        # CH, but that we want to filter the returned results by. This is a hack - it'll break down if
        # the list of valid issue id's is too long, but we do it for now, until we can get issue properties
        # into CH

        use_prefetched = False
        if self.query.issueId:
            # If we have an issueId, we should just use that
            return [self.query.issueId]

        queryset = ErrorTrackingIssue.objects.select_related("assignment").filter(team=self.team)

        if self.query.status and self.query.status not in ["all", "active"]:
            use_prefetched = True
            queryset = queryset.filter(status=self.query.status)

        if self.query.assignee:
            use_prefetched = True
            queryset = (
                queryset.filter(assignment__user_id=self.query.assignee.id)
                if self.query.assignee.type == "user"
                else queryset.filter(assignment__role_id=str(self.query.assignee.id))
            )

        for filter in self.issue_properties:
            queryset = property_to_django_filter(queryset, filter)

        if not use_prefetched:
            return []

        return [str(issue.id) for issue in queryset.only("id").iterator()]

    @cached_property
    def issue_properties(self):
        return [value for value in self.properties if "error_tracking_issue" == value.type]

    @cached_property
    def hogql_properties(self):
        return [value for value in self.properties if "error_tracking_issue" != value.type]

    @cached_property
    def properties(self):
        return self.query.filterGroup.values[0].values if self.query.filterGroup else []


def search_tokenizer(query: str) -> list[str]:
    # parse the search query to split it into words, except for quoted strings. Strip quotes from quoted strings.
    # Example: 'This is a "quoted string" and this is \'another one\' with some words'
    # Output: ['This', 'is', 'a', 'quoted string', 'and', 'this', 'is', 'another one', 'with', 'some', 'words']
    # This doesn't handle nested quotes, and some complex edge cases, but we don't really need that for now.
    # If requirements do change, consider using a proper parser like `pyparsing`
    pattern = r'"[^"]*"|\'[^\']*\'|\S+'
    tokens = re.findall(pattern, query)
    return [token.strip("'\"") for token in tokens]
