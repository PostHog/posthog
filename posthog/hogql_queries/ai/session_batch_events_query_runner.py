from typing import Any

from posthog.schema import (
    CachedSessionBatchEventsQueryResponse,
    EventsQuery,
    SessionBatchEventsQuery,
    SessionBatchEventsQueryResponse,
    SessionEventsItem,
)

from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.session_recordings.constants import (
    DEFAULT_TOTAL_EVENTS_PER_QUERY,
    EXTRA_SUMMARY_EVENT_FIELDS,
    MAX_TOTAL_EVENTS_PER_QUERY,
)
from posthog.session_recordings.queries.session_replay_events import DEFAULT_EVENT_FIELDS

# Type alias for convenience
SessionEventsResults = dict[str, list[list[Any]]]  # session_id -> events mapping


class SessionBatchEventsQueryRunner(QueryRunner):
    """Query runner for batch session event queries using composition with EventsQueryRunner."""

    query: SessionBatchEventsQuery
    cached_response: CachedSessionBatchEventsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Create an EventsQueryRunner for delegation
        self._events_runner = self._create_events_runner()
        # Override the paginator to use our query's limit and offset
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context, limit=self.query.limit, offset=self.query.offset
        )

    def _create_events_runner(self) -> EventsQueryRunner:
        """
        Use composition instead of inheritance to avoid type issues.
        - In `schema-general.ts` -> `SessionBatchEventsQuery` inherit from `EventsQuery`.
        - As it's auto-generated from the schema, inheritance doesn't pass through, while types are compatible.
        - To avoid duplicating lots of code and type issues, use EventsQueryRunner methods where's applicable.
        """
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
            actionId=self.query.actionId,
            personId=self.query.personId,
            filterTestAccounts=self.query.filterTestAccounts,
            source=self.query.source,
        )
        return EventsQueryRunner(
            query=events_query,
            team=self.team,
            timings=self.timings,
            limit_context=self.limit_context,
            modifiers=self.modifiers,
        )

    def to_query(self):
        """Delegate to EventsQueryRunner."""
        return self._events_runner.to_query()

    def columns(self, result_columns):
        """Delegate to EventsQueryRunner."""
        return self._events_runner.columns(result_columns)

    def _calculate(self) -> SessionBatchEventsQueryResponse:
        """
        Execute the session batch query and organize results by session.

        This method uses the paginator to execute the query directly, then post-processes
        the results to group by session.
        """
        # Execute the query using the paginator
        query_result = self.paginator.execute_hogql_query(
            query=self.to_query(),
            team=self.team,
            query_type="SessionBatchEventsQuery",
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        # If group_by_session is False, return the base response as-is, without session_events grouping
        if not self.query.group_by_session:
            return SessionBatchEventsQueryResponse(
                results=self.paginator.results,
                columns=self.columns(query_result.columns),
                types=[t for _, t in query_result.types] if query_result.types else [],
                hogql=query_result.hogql,
                timings=self.timings.to_list(),
                modifiers=self.modifiers,
                session_events=None,
                sessions_with_no_events=[],
                **self.paginator.response_params(),
            )

        # Group results by session and get filtered columns
        session_events_data, filtered_columns = self._group_events_by_session(
            results=self.paginator.results, columns=self.columns(query_result.columns)
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
            results=self.paginator.results,
            columns=filtered_columns,  # Use filtered columns without session_id
            types=[t for _, t in query_result.types] if query_result.types else [],
            hogql=query_result.hogql,
            timings=self.timings.to_list(),
            modifiers=self.modifiers,
            # Session-specific fields
            session_events=session_events,
            sessions_with_no_events=sessions_with_no_events,
            **self.paginator.response_params(),
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
    max_total_events: int = DEFAULT_TOTAL_EVENTS_PER_QUERY,
    offset: int | None = None,
    include_session_id: bool = True,
    **kwargs: Any,
) -> SessionBatchEventsQuery:
    """Create query for getting events for multiple sessions"""
    if max_total_events > MAX_TOTAL_EVENTS_PER_QUERY:
        raise ValueError(f"Max total events per session batch query must be less than {MAX_TOTAL_EVENTS_PER_QUERY}")

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
