from datetime import datetime
from typing import Any, cast

from posthog.schema import AiEventsQuery, CachedEventsQueryResponse, EventsQuery, EventsQueryResponse

from posthog.hogql import ast

from posthog.hogql_queries.ai.ai_property_rewriter import AiPropertyRewriter
from posthog.hogql_queries.ai.ai_table_resolver import (
    is_ai_events_enabled,
    is_within_ai_events_ttl,
    validate_ai_event_names,
)
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
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
        rewritten.select_from = ast.JoinExpr(table=ast.Field(chain=["ai_events"]))
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

    def columns(self, result_columns: list[str]) -> list[str]:
        return self._events_runner.columns(result_columns)
