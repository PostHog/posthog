from datetime import datetime
from typing import Any, cast

from posthog.schema import AiEventsQuery, CachedEventsQueryResponse, EventsQuery, EventsQueryResponse

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor

from posthog.hogql_queries.ai.ai_property_rewriter import AiPropertyRewriter
from posthog.hogql_queries.ai.ai_table_resolver import (
    is_ai_events_enabled,
    is_within_ai_events_ttl,
    validate_ai_event_names,
)
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models.person.util import get_persons_by_distinct_ids
from posthog.utils import relative_date_parse


class AiEventsQueryRunner(QueryRunner):
    """Query runner for AI events that transparently chooses ai_events or events table.

    When the date range is within the 30-day ai_events TTL, queries the ai_events table
    and rewrites `properties.$ai_*` references to dedicated column names.
    Beyond the TTL, falls back to the standard events table.
    """

    query: AiEventsQuery
    cached_response: CachedEventsQueryResponse

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._events_runner = self._create_events_runner()
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context,
            limit=self.query.limit,
            offset=self.query.offset,
        )

    def _create_events_runner(self) -> EventsQueryRunner:
        events_query = EventsQuery(
            kind="EventsQuery",
            select=self.query.select,
            where=self.query.where,
            properties=self.query.properties,
            fixedProperties=self.query.fixedProperties,
            orderBy=self.query.orderBy,
            limit=self.query.limit,
            offset=self.query.offset,
            after=self.query.after,
            before=self.query.before,
            event=self.query.event,
            events=self.query.events,
            actionId=self.query.actionId,
            personId=self.query.personId,
            filterTestAccounts=self.query.filterTestAccounts,
        )
        return EventsQueryRunner(
            query=events_query,
            team=self.team,
            timings=self.timings,
            limit_context=self.limit_context,
            modifiers=self.modifiers,
        )

    def _should_use_ai_events_table(self) -> bool:
        if not is_ai_events_enabled(self.team):
            return False

        after = self.query.after or "-24h"
        if after == "all":
            return False

        now = datetime.now(tz=self.team.timezone_info)
        date_from = relative_date_parse(after, self.team.timezone_info)
        if not is_within_ai_events_ttl(date_from, now):
            return False

        # If 'before' is explicitly set beyond TTL, fall back to events
        if self.query.before:
            date_to = relative_date_parse(self.query.before, self.team.timezone_info)
            if not is_within_ai_events_ttl(date_to, now):
                return False

        return True

    def _validate(self) -> None:
        event_names: list[str] = []
        if self.query.event:
            event_names.append(self.query.event)
        if self.query.events:
            event_names.extend(self.query.events)
        if event_names:
            validate_ai_event_names(event_names)

    def to_query(self) -> ast.SelectQuery:
        query_ast = self._events_runner.to_query()
        if self._should_use_ai_events_table():
            query_ast = self._rewrite_for_ai_events(query_ast)
        return query_ast

    def _rewrite_for_ai_events(self, query: ast.SelectQuery) -> ast.SelectQuery:
        rewritten = cast(ast.SelectQuery, AiPropertyRewriter().visit(query))
        rewritten = cast(ast.SelectQuery, _EventsToAiEventsTableRewriter().visit(rewritten))
        return rewritten

    def _calculate(self) -> EventsQueryResponse:
        self._validate()

        # If we should use ai_events, rewrite and execute directly
        if self._should_use_ai_events_table():
            query_result = self.paginator.execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="AiEventsQuery",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

            self._enrich_persons()

            return EventsQueryResponse(
                results=self.paginator.results,
                columns=self._events_runner.columns(query_result.columns),
                types=[t for _, t in query_result.types] if query_result.types else [],
                hogql=query_result.hogql,
                timings=self.timings.to_list(),
                modifiers=self.modifiers,
                **self.paginator.response_params(),
            )

        # Fall back to standard EventsQueryRunner
        return self._events_runner.calculate()

    def _enrich_persons(self) -> None:
        """Person enrichment — duplicated from EventsQueryRunner._calculate()
        to derisk any effect on normal event queries. Can be refactored into
        a shared method once the ai_events migration is stable."""
        person_indices: list[int] = []
        for column_index, col in enumerate(self._events_runner.select_input_raw()):
            if col.split("--")[0].strip() == "person":
                person_indices.append(column_index)
            if col.split("--")[0].strip() == "person_display_name":
                for index, result in enumerate(self.paginator.results):
                    row = list(self.paginator.results[index])
                    row[column_index] = {
                        "display_name": result[column_index][0],
                        "id": str(result[column_index][1]),
                        "distinct_id": str(result[column_index][2]),
                    }
                    self.paginator.results[index] = row

        if len(person_indices) > 0 and len(self.paginator.results) > 0:
            with self.timings.measure("person_column_extra_query"):
                person_idx = person_indices[0]
                distinct_ids = list({event[person_idx] for event in self.paginator.results})

                distinct_to_person: dict[str, Any] = {}
                batch_size = 1000
                for i in range(0, len(distinct_ids), batch_size):
                    batch_distinct_ids = distinct_ids[i : i + batch_size]
                    requested_batch = set(batch_distinct_ids)
                    persons = get_persons_by_distinct_ids(self.team.pk, batch_distinct_ids)
                    for person in persons:
                        if person:
                            for person_distinct_id in person.distinct_ids:
                                if person_distinct_id in requested_batch:
                                    distinct_to_person[person_distinct_id] = person

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

    def columns(self, result_columns: list[str]) -> list[str]:
        return self._events_runner.columns(result_columns)


class _EventsToAiEventsTableRewriter(CloningVisitor):
    """Swaps all `FROM events` table references to `FROM ai_events` throughout the AST.

    The EventsQueryRunner may produce nested subqueries (e.g. presorted optimization)
    that also reference the events table, so a top-level-only swap is insufficient.
    """

    def visit_join_expr(self, node: ast.JoinExpr) -> ast.JoinExpr:
        new_node = super().visit_join_expr(node)
        if isinstance(new_node.table, ast.Field) and new_node.table.chain == ["events"]:
            new_node.table = ast.Field(chain=["ai_events"])
        return new_node
