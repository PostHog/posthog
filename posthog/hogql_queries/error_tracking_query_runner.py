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
from posthog.models.person.util import get_persons_by_distinct_ids
from django.db.models import Prefetch
from posthog.models import Person


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

        if self.query.eventColumns:
            # replace person distinct_id that can be looked up in Postgres later
            event_columns = ["distinct_id" if el == "person" else el for el in self.query.eventColumns]
            args: list[ast.Expr] = [ast.Field(chain=[field]) for field in event_columns]
            exprs.append(
                ast.Alias(
                    alias="events",
                    expr=ast.Call(
                        name="groupArray",
                        args=[
                            ast.Call(
                                name="tuple",
                                args=args,
                            )
                        ],
                    ),
                )
            )

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
                                self.group_fingerprints(group),
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

        if self.query.fingerprint:
            group = self.group_or_default(self.query.fingerprint)
            exprs.append(
                ast.Call(
                    name="has",
                    args=[
                        self.group_fingerprints(group),
                        self.extracted_fingerprint_property(),
                    ],
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

    def results(self, columns: list[str], query_results: list):
        mapped_results = [dict(zip(columns, value)) for value in query_results]
        results = []
        for result_dict in mapped_results:
            fingerprint = self.query.fingerprint if self.query.fingerprint else result_dict["fingerprint"]
            group = self.group_or_default(fingerprint)

            if self.query.eventColumns:
                result_dict["events"] = self.parse_embedded_events_and_persons(
                    self.query.eventColumns, result_dict.get("events", [])
                )

            results.append(result_dict | group)

        return results

    def parse_embedded_events_and_persons(self, columns: list[str], events: list):
        person_indices: list[int] = []
        for index, col in enumerate(columns):
            if col == "person":
                person_indices.append(index)

        if len(person_indices) > 0 and len(events) > 0:
            person_idx = person_indices[0]
            distinct_ids = list({event[person_idx] for event in events})
            persons = get_persons_by_distinct_ids(self.team.pk, distinct_ids)
            persons = persons.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
            distinct_to_person: dict[str, Person] = {}
            for person in persons:
                if person:
                    for person_distinct_id in person.distinct_ids:
                        distinct_to_person[person_distinct_id] = person

            for column_index in person_indices:
                for index, result in enumerate(events):
                    distinct_id: str = result[column_index]
                    events[index] = list(result)
                    if distinct_to_person.get(distinct_id):
                        person = distinct_to_person[distinct_id]
                        events[index][column_index] = {
                            "uuid": person.uuid,
                            "created_at": person.created_at,
                            "properties": person.properties or {},
                            "distinct_id": distinct_id,
                        }
                    else:
                        events[index][column_index] = {
                            "distinct_id": distinct_id,
                        }

        return [dict(zip(columns, value)) for value in events]

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

    def group_fingerprints(self, group):
        exprs: list[ast.Expr] = [ast.Constant(value=group["fingerprint"])]
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
        groups = queryset.values("fingerprint", "merged_fingerprints", "status", "assignee")
        return {str(item["fingerprint"]): item for item in groups}
