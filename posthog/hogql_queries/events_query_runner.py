from datetime import timedelta
from functools import cached_property
from typing import Any, Optional, cast
import re

from django.db.models import Prefetch
from django.utils.timezone import now
import orjson

from ee.session_recordings.session_summary.input_data import EXTRA_SUMMARY_EVENT_FIELDS
from posthog.api.element import ElementSerializer
from posthog.api.utils import get_pk_or_uuid
from posthog.hogql import ast
from posthog.hogql.ast import Alias
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_select
from posthog.hogql.property import action_to_expr, has_aggregation, property_to_expr
from posthog.hogql_queries.insights.insight_actors_query_runner import InsightActorsQueryRunner
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models import Action, Person
from posthog.models.element import chain_to_elements
from posthog.models.person.person import READ_DB_FOR_PERSONS, get_distinct_ids_for_subquery
from posthog.models.person.util import get_persons_by_distinct_ids
from posthog.schema import (
    CachedSessionBatchEventsQueryResponse,
    DashboardFilter,
    EventsQuery,
    EventsQueryResponse,
    CachedEventsQueryResponse,
    SessionBatchEventsQuery,
    SessionBatchEventsQueryResponse,
    SessionEventsItem,
    SessionEventsResults,
)
from posthog.utils import relative_date_parse
from posthog.api.person import PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
from posthog.session_recordings.queries.session_replay_events import DEFAULT_EVENT_FIELDS

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

    @cached_property
    def source_runner(self) -> InsightActorsQueryRunner:
        if not self.query.source:
            raise ValueError("Source query is required")

        return cast(
            InsightActorsQueryRunner,
            get_query_runner(self.query.source, self.team, self.timings, self.limit_context, self.modifiers),
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
            elif col.split("--")[0].strip() == "person_display_name":
                property_keys = self.team.person_display_name_properties or PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
                # Only use backticks for property names with spaces or special chars
                props = []
                for key in property_keys:
                    if re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", key):
                        props.append(f"toString(person.properties.{key})")
                    else:
                        props.append(f"toString(person.properties.`{key}`)")
                expr = f"(coalesce({', '.join([*props, 'distinct_id'])}), toString(person.id))"
                select_input.append(expr)
            else:
                select_input.append(col)
        return select_input, [parse_expr(column, timings=self.timings) for column in select_input]

    def to_query(self) -> ast.SelectQuery:
        # Note: This code is inefficient and problematic, see https://github.com/PostHog/posthog/issues/13485 for details.
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
                            action = Action.objects.get(pk=self.query.actionId, team__project_id=self.team.project_id)
                        except Action.DoesNotExist:
                            raise Exception("Action does not exist")
                        if not action.steps:
                            raise Exception("Action does not have any match groups")
                        where_exprs.append(action_to_expr(action))
                if self.query.personId:
                    with self.timings.measure("person_id"):
                        person: Optional[Person] = get_pk_or_uuid(
                            Person.objects.db_manager(READ_DB_FOR_PERSONS).filter(team=self.team), self.query.personId
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
                where: ast.Expr | None = ast.And(exprs=where_list) if len(where_list) > 0 else None
                having_list = [expr for expr in where_exprs if has_aggregation(expr)]
                having: ast.Expr | None = ast.And(exprs=having_list) if len(having_list) > 0 else None

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
                if self.query.source is not None:
                    # Kludge: If the events_query has logic in select that the where clauses depends on, this will potentially error.
                    # If we implement that for other runners, make this smarter.
                    events_query = self.source_runner.to_events_query()
                    events_query.select = select
                    if where is not None:
                        if events_query.where is None:
                            events_query.where = where
                        else:
                            events_query.where = ast.And(exprs=[events_query.where, where])
                    if having is not None:
                        if events_query.having is None:
                            events_query.having = having
                        else:
                            events_query.having = ast.And(exprs=[events_query.having, having])
                    events_query.group_by = group_by if has_any_aggregation else None
                    events_query.order_by = order_by
                    return events_query

                stmt = ast.SelectQuery(
                    select=select,
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    where=where,
                    having=having,
                    group_by=group_by if has_any_aggregation else None,
                    order_by=order_by,
                )

                # sorting a large amount of columns is expensive, so we filter by a presorted table if possible
                if (
                    self.modifiers.usePresortedEventsTable
                    and (
                        order_by is not None
                        and len(order_by) == 1
                        and isinstance(order_by[0].expr, ast.Field)
                        and order_by[0].expr.chain == ["timestamp"]
                    )
                    and not has_any_aggregation
                ):
                    inner_query = parse_select(
                        "SELECT timestamp, event, cityHash64(distinct_id), cityHash64(uuid) FROM events"
                    )
                    assert isinstance(inner_query, ast.SelectQuery)
                    inner_query.where = where
                    inner_query.order_by = order_by
                    self.paginator.paginate(inner_query)

                    # prefilter the events table based on the sort order with a narrow set of columns
                    prefilter_sorted = parse_expr(
                        "(timestamp, event, cityHash64(distinct_id), cityHash64(uuid)) in ({inner_query})",
                        {"inner_query": inner_query},
                    )

                    if where is not None:
                        stmt.where = ast.And(exprs=[prefilter_sorted, where])
                    else:
                        stmt.where = prefilter_sorted

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
        for column_index, col in enumerate(self.select_input_raw()):
            if col.split("--")[0].strip() == "person":
                person_indices.append(column_index)
            # convert tuple that gets returned into a dict
            if col.split("--")[0].strip() == "person_display_name":
                for index, result in enumerate(self.paginator.results):
                    row = list(self.paginator.results[index])
                    row[column_index] = {
                        "display_name": result[column_index][0],
                        "id": str(result[column_index][1]),
                    }
                    self.paginator.results[index] = row

        # TODO: get rid of this logic once we don't use `person` columns anywhere
        if len(person_indices) > 0 and len(self.paginator.results) > 0:
            with self.timings.measure("person_column_extra_query"):
                # Make a query into postgres to fetch person
                person_idx = person_indices[0]
                distinct_ids = list({event[person_idx] for event in self.paginator.results})

                distinct_to_person: dict[str, Person] = {}
                # Process distinct_ids in batches to avoid overwhelming PostgreSQL
                batch_size = 1000
                for i in range(0, len(distinct_ids), batch_size):
                    batch_distinct_ids = distinct_ids[i : i + batch_size]
                    persons = get_persons_by_distinct_ids(self.team.pk, batch_distinct_ids)
                    persons = persons.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
                    for person in persons.iterator(chunk_size=1000):
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
            types=[t for _, t in query_result.types] if query_result.types else [],
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


class SessionBatchEventsQueryRunner(EventsQueryRunner):
    """Extended EventsQueryRunner for batch session event queries. Keeping in the same class as EventsQueryRunner to avoid circular imports."""

    query: SessionBatchEventsQuery
    response: SessionBatchEventsQueryResponse
    cached_response: CachedSessionBatchEventsQueryResponse

    def calculate(self) -> SessionBatchEventsQueryResponse:
        """
        Execute the session batch query and organize results by session.

        This method leverages the parent EventsQueryRunner.calculate() for query execution,
        then post-processes the results to group by session.
        """
        # Execute the base query using parent EventsQueryRunner
        base_response = super().calculate()
        # If group_by_session is False, return the base response as-is, without session_events grouping
        if not self.query.group_by_session:
            return SessionBatchEventsQueryResponse(
                **base_response.model_dump(),
                session_events=None,
            )
        # Group results by session and get filtered columns
        session_events_data, filtered_columns = self._group_events_by_session(
            results=base_response.results, columns=base_response.columns or []
        )
        # Create SessionEventsItem list to split the results into sessions with or without events
        session_events: list[SessionEventsItem] = []
        sessions_with_no_events: list[str] = []
        for session_id in self.query.session_ids:
            if session_id in session_events_data:
                events = session_events_data[session_id]
                session_events.append(
                    SessionEventsItem(
                        session_id=session_id,
                        events=events,
                    )
                )
            else:
                sessions_with_no_events.append(session_id)
        return SessionBatchEventsQueryResponse(
            # Base EventsQueryResponse fields
            results=base_response.results,
            columns=filtered_columns,  # Use filtered columns without session_id
            types=base_response.types,
            hogql=base_response.hogql,
            timings=base_response.timings,
            error=base_response.error,
            hasMore=base_response.hasMore,
            limit=base_response.limit,
            offset=base_response.offset,
            modifiers=base_response.modifiers,
            query_status=base_response.query_status,
            # Session-specific fields
            session_events=session_events,
            sessions_with_no_events=sessions_with_no_events,
        )

    def _group_events_by_session(
        self, results: list[list[Any]], columns: list[str]
    ) -> tuple[SessionEventsResults, list[str]]:
        """Group query results by session_id."""
        if not results or not columns:
            return {}, columns
        # Find the index of the $session_id column
        session_id_index = None
        for i, col in enumerate(columns):
            if col in ["properties.$session_id", "$session_id"]:
                session_id_index = i
                break
        if session_id_index is None:
            # If no session_id column found, we can't group by session
            # This shouldn't happen if the query was constructed properly
            raise ValueError(
                "No session_id column found in query results. Ensure 'properties.$session_id' is included in the select clause."
            )
        # Create filtered columns list without the session_id column
        filtered_columns = columns[:session_id_index] + columns[session_id_index + 1 :]
        # Group events by session_id
        events_by_session: SessionEventsResults = {}
        for row in results:
            if len(row) <= session_id_index:
                continue
            session_id = row[session_id_index]
            if session_id is None:
                continue
            # Convert to string to ensure consistent typing
            session_id = str(session_id)

            if session_id not in events_by_session:
                events_by_session[session_id] = []
            # Remove the session_id from the row since it's used for grouping
            # Keep all other fields for the session's events
            event_row = list(row[:session_id_index]) + list(row[session_id_index + 1 :])
            events_by_session[session_id].append(event_row)
        return events_by_session, filtered_columns


def create_session_batch_events_query(
    session_ids: list[str],
    select: list[str] | None = None,
    events_to_ignore: list[str] | None = None,
    after: str | None = None,
    before: str | None = None,
    max_total_events: int | None = None,
    offset: int | None = None,
    include_session_id: bool = True,
    **kwargs: Any,
) -> SessionBatchEventsQuery:
    """Create query for getting events for multiple sessions"""

    # Default field selection for session summaries
    if select is None:
        select = DEFAULT_EVENT_FIELDS + EXTRA_SUMMARY_EVENT_FIELDS

    # Ensure $session_id is included for grouping
    if include_session_id and "properties.$session_id" not in select:
        select.append("properties.$session_id")

    # Build WHERE clauses for session filtering and event exclusion
    where_clauses = [f"properties.$session_id IN {session_ids}"]  # Filter by session IDs by default

    # Exclude unwanted events (default to ignoring feature flag calls)
    if events_to_ignore is None:
        events_to_ignore = ["$feature_flag_called"]
    if events_to_ignore:
        event_list = "', '".join(events_to_ignore)
        where_clauses.append(f"event NOT IN ('{event_list}')")

    # Combine with any existing where clauses, if provided
    existing_where = kwargs.get("where", [])
    if isinstance(existing_where, list):
        where_clauses.extend(existing_where)

    # Set defaults for session batch queries
    query_params = {
        "select": select,
        "session_ids": session_ids,
        "where": where_clauses,
        "orderBy": ["properties.$session_id", "timestamp ASC"],  # Group by session, then chronological
        "limit": max_total_events,
        "offset": offset,
        "group_by_session": True,
        "after": after,
        "before": before,
        **kwargs,  # Allow overriding defaults
    }
    return SessionBatchEventsQuery(**query_params)
