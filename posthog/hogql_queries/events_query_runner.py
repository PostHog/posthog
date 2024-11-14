from datetime import timedelta
from typing import Optional

from django.db.models import Prefetch
from django.utils.timezone import now
import orjson

from posthog.api.element import ElementSerializer
from posthog.api.utils import get_pk_or_uuid
from posthog.hogql import ast
from posthog.hogql.ast import Alias
from posthog.hogql.parser import parse_expr, parse_order_expr
from posthog.hogql.property import action_to_expr, has_aggregation, property_to_expr
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models import Action, Person
from posthog.models.element import chain_to_elements
from posthog.models.person.person import get_distinct_ids_for_subquery
from posthog.models.person.util import get_persons_by_distinct_ids
from posthog.schema import DashboardFilter, EventsQuery, EventsQueryResponse, CachedEventsQueryResponse
from posthog.utils import relative_date_parse

# Allow-listed fields returned when you select "*" from events. Person and group fields will be nested later.
SELECT_STAR_FROM_EVENTS_FIELDS = [
    "uuid",
    "event",
    "properties",
    "timestamp",
    "team_id",
    "distinct_id",
    "elements_chain",
    "created_at",
]


class EventsQueryRunner(QueryRunner):
    query: EventsQuery
    response: EventsQueryResponse
    cached_response: CachedEventsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context, limit=self.query.limit, offset=self.query.offset
        )

    def select_cols(self) -> tuple[list[str], list[ast.Expr]]:
        select_input: list[str] = []
        person_indices: list[int] = []
        for index, col in enumerate(self.select_input_raw()):
            # Selecting a "*" expands the list of columns, resulting in a table that's not what we asked for.
            # Instead, ask for a tuple with all the columns we want. Later transform this back into a dict.
            if col == "*":
                select_input.append(f"tuple({', '.join(SELECT_STAR_FROM_EVENTS_FIELDS)})")
            elif col.split("--")[0].strip() == "person":
                # This will be expanded into a followup query
                select_input.append("distinct_id")
                person_indices.append(index)
            else:
                select_input.append(col)
        return select_input, [parse_expr(column, timings=self.timings) for column in select_input]

    def to_query(self) -> ast.SelectQuery:
        # Note: This code is inefficient and problematic, see https://github.com/PostHog/posthog/issues/13485 for details.
        if self.timings is None:
            self.timings = HogQLTimings()

        with self.timings.measure("build_ast"):
            # columns & group_by
            with self.timings.measure("columns"):
                select_input, select = self.select_cols()

            with self.timings.measure("aggregations"):
                group_by: list[ast.Expr] = [column for column in select if not has_aggregation(column)]
                aggregations: list[ast.Expr] = [column for column in select if has_aggregation(column)]
                has_any_aggregation = len(aggregations) > 0

            # filters
            with self.timings.measure("filters"):
                with self.timings.measure("where"):
                    where_input = self.query.where or []
                    where_exprs = [parse_expr(expr, timings=self.timings) for expr in where_input]
                if self.query.properties:
                    with self.timings.measure("properties"):
                        where_exprs.extend(property_to_expr(property, self.team) for property in self.query.properties)
                if self.query.fixedProperties:
                    with self.timings.measure("fixed_properties"):
                        where_exprs.extend(
                            property_to_expr(property, self.team) for property in self.query.fixedProperties
                        )
                if self.query.event:
                    with self.timings.measure("event"):
                        where_exprs.append(
                            parse_expr(
                                "event = {event}",
                                {"event": ast.Constant(value=self.query.event)},
                                timings=self.timings,
                            )
                        )
                if self.query.actionId:
                    with self.timings.measure("action_id"):
                        try:
                            action = Action.objects.get(pk=self.query.actionId, team_id=self.team.pk)
                        except Action.DoesNotExist:
                            raise Exception("Action does not exist")
                        if not action.steps:
                            raise Exception("Action does not have any match groups")
                        where_exprs.append(action_to_expr(action))
                if self.query.personId:
                    with self.timings.measure("person_id"):
                        person: Optional[Person] = get_pk_or_uuid(
                            Person.objects.filter(team=self.team), self.query.personId
                        ).first()
                        where_exprs.append(
                            ast.CompareOperation(
                                left=ast.Call(name="cityHash64", args=[ast.Field(chain=["distinct_id"])]),
                                right=ast.Tuple(
                                    exprs=[
                                        ast.Call(name="cityHash64", args=[ast.Constant(value=id)])
                                        for id in get_distinct_ids_for_subquery(person, self.team)
                                    ]
                                ),
                                op=ast.CompareOperationOp.In,
                            )
                        )
                if self.query.filterTestAccounts:
                    with self.timings.measure("test_account_filters"):
                        for prop in self.team.test_account_filters or []:
                            where_exprs.append(property_to_expr(prop, self.team))

            with self.timings.measure("timestamps"):
                # prevent accidentally future events from being visible by default
                before = self.query.before or (now() + timedelta(seconds=5)).isoformat()
                parsed_date = relative_date_parse(before, self.team.timezone_info)
                where_exprs.append(
                    parse_expr(
                        "timestamp < {timestamp}",
                        {"timestamp": ast.Constant(value=parsed_date)},
                        timings=self.timings,
                    )
                )

                # limit to the last 24h by default
                after = self.query.after or "-24h"
                if after != "all":
                    parsed_date = relative_date_parse(after, self.team.timezone_info)
                    where_exprs.append(
                        parse_expr(
                            "timestamp > {timestamp}",
                            {"timestamp": ast.Constant(value=parsed_date)},
                            timings=self.timings,
                        )
                    )

            # where & having
            with self.timings.measure("where"):
                where_list = [expr for expr in where_exprs if not has_aggregation(expr)]
                where = ast.And(exprs=where_list) if len(where_list) > 0 else None
                having_list = [expr for expr in where_exprs if has_aggregation(expr)]
                having = ast.And(exprs=having_list) if len(having_list) > 0 else None

            # order by
            with self.timings.measure("order"):
                if self.query.orderBy is not None:
                    order_by = [parse_order_expr(column, timings=self.timings) for column in self.query.orderBy]
                elif "count()" in select_input:
                    order_by = [ast.OrderExpr(expr=parse_expr("count()"), order="DESC")]
                elif len(aggregations) > 0:
                    order_by = [ast.OrderExpr(expr=aggregations[0], order="DESC")]
                elif "timestamp" in select_input:
                    order_by = [ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")]
                elif len(select) > 0:
                    order_by = [ast.OrderExpr(expr=select[0], order="ASC")]
                else:
                    order_by = []

            with self.timings.measure("select"):
                stmt = ast.SelectQuery(
                    select=select,
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    where=where,
                    having=having,
                    group_by=group_by if has_any_aggregation else None,
                    order_by=order_by,
                )
                return stmt

    def calculate(self) -> EventsQueryResponse:
        query_result = self.paginator.execute_hogql_query(
            query=self.to_query(),
            team=self.team,
            query_type="EventsQuery",
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        # Convert star field from tuple to dict in each result
        if "*" in self.select_input_raw():
            with self.timings.measure("expand_asterisk"):
                star_idx = self.select_input_raw().index("*")
                for index, result in enumerate(self.paginator.results):
                    self.paginator.results[index] = list(result)
                    select = result[star_idx]
                    new_result = dict(zip(SELECT_STAR_FROM_EVENTS_FIELDS, select))
                    new_result["properties"] = orjson.loads(new_result["properties"])
                    if new_result["elements_chain"]:
                        new_result["elements"] = ElementSerializer(
                            chain_to_elements(new_result["elements_chain"]), many=True
                        ).data
                    self.paginator.results[index][star_idx] = new_result

        person_indices: list[int] = []
        for index, col in enumerate(self.select_input_raw()):
            if col.split("--")[0].strip() == "person":
                person_indices.append(index)

        if len(person_indices) > 0 and len(self.paginator.results) > 0:
            with self.timings.measure("person_column_extra_query"):
                # Make a query into postgres to fetch person
                person_idx = person_indices[0]
                distinct_ids = list({event[person_idx] for event in self.paginator.results})
                persons = get_persons_by_distinct_ids(self.team.pk, distinct_ids)
                persons = persons.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
                distinct_to_person: dict[str, Person] = {}
                for person in persons:
                    if person:
                        for person_distinct_id in person.distinct_ids:
                            distinct_to_person[person_distinct_id] = person

                # Loop over all columns in case there is more than one "person" column
                for column_index in person_indices:
                    for index, result in enumerate(self.paginator.results):
                        distinct_id: str = result[column_index]
                        self.paginator.results[index] = list(result)
                        if distinct_to_person.get(distinct_id):
                            person = distinct_to_person[distinct_id]
                            self.paginator.results[index][column_index] = {
                                "uuid": person.uuid,
                                "created_at": person.created_at,
                                "properties": person.properties or {},
                                "distinct_id": distinct_id,
                            }
                        else:
                            self.paginator.results[index][column_index] = {
                                "distinct_id": distinct_id,
                            }

        return EventsQueryResponse(
            results=self.paginator.results,
            columns=self.columns(query_result.columns),
            types=[t for _, t in query_result.types] if query_result.types else None,
            timings=self.timings.to_list(),
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter):
        if dashboard_filter.date_to or dashboard_filter.date_from:
            self.query.before = dashboard_filter.date_to
            self.query.after = dashboard_filter.date_from

        if dashboard_filter.properties:
            self.query.properties = (self.query.properties or []) + dashboard_filter.properties

    def columns(self, result_columns: list | None) -> list[str]:
        _, select = self.select_cols()
        columns = result_columns or []
        return [
            columns[idx] if len(columns) > idx and isinstance(select[idx], Alias) else col
            for idx, col in enumerate(self.select_input_raw())
        ]

    def select_input_raw(self) -> list[str]:
        return ["*"] if len(self.query.select) == 0 else self.query.select
