"""
QueryRunner implementation for fetching session events for multiple sessions in a single query.
This is designed to optimize session summary generation by reducing the number of database queries
from N (one per session) to 1 (for all sessions in batch).

This QueryRunner is specifically designed for session summary use cases and should not replace
the existing SessionReplayEvents.get_events() method for single session queries.
"""

# dataclass removed since SessionEventsBatch is now a Pydantic model
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.query_runner import QueryRunner
from .schema import (
    CachedMultiSessionEventsQueryResponse,
    MultiSessionEventsQuery,
    MultiSessionEventsQueryResponse,
    MultiSessionEventsItem,
    SessionEventsBatch,
)
from posthog.session_recordings.models.metadata import RecordingMetadata

# Default fields that are always included in session events queries
DEFAULT_EVENT_FIELDS = [
    "event",
    "timestamp",
    "elements_chain_href",
    "elements_chain_texts",
    "elements_chain_elements",
    "properties.$window_id",
    "properties.$current_url",
    "properties.$event_type",
]

# Additional fields typically needed for session summary analysis
EXTRA_SUMMARY_EVENT_FIELDS = [
    "elements_chain_ids",
    "elements_chain",
    "properties.$exception_types",
    "properties.$exception_sources",
    "properties.$exception_values",
    "properties.$exception_fingerprint_record",
    "properties.$exception_functions",
    "uuid",
]


# SessionEventsBatch is now imported from schema.py


class MultiSessionEventsQueryRunner(QueryRunner):
    """
    QueryRunner for fetching events from multiple sessions in a single optimized query.
    
    This runner is specifically designed for session summary workflows where we need
    to fetch events for multiple sessions efficiently. It constructs a single HogQL query
    that fetches events for all requested sessions, reducing database round trips.
    
    Key optimizations:
    1. Single query for multiple sessions instead of N queries
    2. Proper time range filtering based on session metadata
    3. Built-in pagination and limiting per session
    4. Standardized field selection for session summary use cases
    """
    
    query: MultiSessionEventsQuery
    response: MultiSessionEventsQueryResponse
    cached_response: CachedMultiSessionEventsQueryResponse

    def calculate(self) -> MultiSessionEventsQueryResponse:
        """
        Main calculation method that executes the multi-session events query.
        
        Returns:
            MultiSessionEventsQueryResponse containing events grouped by session_id
        """
        # Build the HogQL query for multiple sessions
        query = self.to_query()
        
        # Convert to printed HogQL for debugging and response metadata
        hogql = to_printed_hogql(query, self.team)
        
        # Execute the query using PostHog's query execution infrastructure
        response = execute_hogql_query(
            query_type="MultiSessionEventsQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        
        # Group results by session_id and convert to structured format
        events_by_session = self._group_events_by_session(response.results)
        
        # Convert to typed response items
        session_events: List[MultiSessionEventsItem] = []
        for session_id, events in events_by_session.items():
            session_events.append(
                MultiSessionEventsItem(
                    session_id=session_id,
                    events=events,
                    event_count=len(events),
                )
            )
        
        return MultiSessionEventsQueryResponse(
            session_events=session_events,
            columns=response.columns or [],
            types=response.types or [],
            total_sessions=len(session_events),
            total_events=sum(item.event_count for item in session_events),
            timings=response.timings,
            hogql=hogql,
            modifiers=self.modifiers,
        )

    def to_query(self) -> ast.SelectQuery:
        """
        Constructs the HogQL query for fetching events from multiple sessions.
        
        This method builds a single query that efficiently fetches events for all
        requested sessions by:
        1. Using IN clause for session_ids
        2. Applying time range filters based on session metadata
        3. Including proper field selection and ordering
        4. Applying limits and pagination as needed
        
        Returns:
            ast.SelectQuery: The constructed HogQL query
        """
        batch = self.query.session_batch
        
        # Build the field list - always include defaults plus any extra fields
        fields = DEFAULT_EVENT_FIELDS.copy()
        if batch.extra_fields:
            fields.extend(batch.extra_fields)
        
        # Add session_id to fields so we can group results by session
        if "$session_id" not in fields:
            fields.append("$session_id")
        
        # Create the base SELECT query
        query_parts = [
            f"SELECT {', '.join(fields)}",
            "FROM events",
            "WHERE"
        ]
        
        # Build WHERE conditions
        where_conditions = []
        
        # Filter by session IDs
        where_conditions.append("$session_id IN {session_ids}")
        
        # Apply time range filtering based on session metadata
        # We need to accommodate all sessions, so we use the earliest start time
        # and latest end time across all sessions (with some buffer)
        # Note: batch.session_metadata would need to be passed separately or included in the schema
        # For now, we'll use the date_range if provided
        if batch.date_range:
            earliest_start = batch.date_range.date_from
            latest_end = batch.date_range.date_to or batch.date_range.date_from
        else:
            # Fallback - this would need session metadata to be properly implemented
            from datetime import datetime
            earliest_start = datetime.now() - timedelta(days=7)
            latest_end = datetime.now()
        
        where_conditions.append("timestamp >= {earliest_start}")
        where_conditions.append("timestamp <= {latest_end}")
        
        # Filter out events we want to ignore (e.g., feature flag calls)
        if batch.events_to_ignore:
            where_conditions.append("event NOT IN {events_to_ignore}")
        
        # Join WHERE conditions
        query_parts.append(" AND ".join(where_conditions))
        
        # Order by session_id and timestamp for consistent results
        query_parts.append("ORDER BY $session_id, timestamp ASC")
        
        # Apply global limit if specified
        if batch.max_total_events:
            query_parts.append(f"LIMIT {batch.max_total_events}")
        
        # Build the complete query string
        query_string = " ".join(query_parts)
        
        # Parse the query string into AST with proper placeholders
        return parse_select(
            query_string,
            placeholders={
                "session_ids": ast.Constant(value=batch.session_ids),
                "earliest_start": ast.Constant(value=earliest_start),
                "latest_end": ast.Constant(value=latest_end),
                "events_to_ignore": ast.Constant(value=batch.events_to_ignore) if batch.events_to_ignore else None,
            },
        )

    def _group_events_by_session(self, results: List[List[Any]]) -> Dict[str, List[Tuple[Any, ...]]]:
        """
        Groups query results by session_id for easier processing.
        
        Args:
            results: Raw query results from the database
            
        Returns:
            Dictionary mapping session_id to list of events for that session
        """
        events_by_session: Dict[str, List[Tuple[Any, ...]]] = {}
        
        # Find the index of the $session_id field in the results
        # This assumes $session_id is included in the selected fields
        session_id_index = -1  # Will be set to the actual index
        
        for row in results:
            if len(row) == 0:
                continue
            
            # Get session_id from the row (assuming it's the last field we added)
            session_id = row[session_id_index]
            
            if session_id not in events_by_session:
                events_by_session[session_id] = []
            
            # Add the event to the session's event list
            # Remove the session_id from the row since it's only needed for grouping
            event_row = tuple(row[:session_id_index] + row[session_id_index + 1:])
            events_by_session[session_id].append(event_row)
        
        # Apply per-session limits if specified
        batch = self.query.session_batch
        if batch.limit_per_session:
            for session_id in events_by_session:
                events_by_session[session_id] = events_by_session[session_id][:batch.limit_per_session]
        
        return events_by_session

    def _validate_session_batch(self, batch: SessionEventsBatch) -> None:
        """
        Validates that the session batch contains all required data.
        
        Args:
            batch: The session batch to validate
            
        Raises:
            ValueError: If the batch is invalid
        """
        if not batch.session_ids:
            raise ValueError("Session batch must contain at least one session_id")
        
        # Note: With the Pydantic model, basic validation is handled automatically
        # Additional business logic validation can be added here if needed


def create_session_events_batch(
    session_ids: List[str],
    events_to_ignore: Optional[List[str]] = None,
    extra_fields: Optional[List[str]] = None,
    limit_per_session: Optional[int] = None,
    max_total_events: Optional[int] = None,
    date_range: Optional[Any] = None,  # DateRange from schema
) -> SessionEventsBatch:
    """
    Convenience function to create a SessionEventsBatch with proper validation.
    
    Args:
        session_ids: List of session IDs to fetch events for
        events_to_ignore: List of event names to exclude from results
        extra_fields: Additional fields to include beyond the defaults
        limit_per_session: Maximum number of events per session
        max_total_events: Maximum total events across all sessions
        date_range: Optional date range for filtering events
        
    Returns:
        SessionEventsBatch: Configured batch ready for querying
    """
    # Use session summary defaults if not specified
    if events_to_ignore is None:
        events_to_ignore = ["$feature_flag_called"]
    
    if extra_fields is None:
        extra_fields = EXTRA_SUMMARY_EVENT_FIELDS
    
    return SessionEventsBatch(
        session_ids=session_ids,
        events_to_ignore=events_to_ignore,
        extra_fields=extra_fields,
        limit_per_session=limit_per_session,
        max_total_events=max_total_events,
        date_range=date_range,
    )


# Example usage for session summary workflows:
"""
# Instead of making N separate queries:
for session_id in session_ids:
    events = get_session_events(session_id, metadata, team_id)
    
# Use a single optimized query:
batch = create_session_events_batch(
    session_ids=session_ids,
    limit_per_session=3000,  # Match current pagination limit
    max_total_events=10000,  # Prevent excessive memory usage
)

query = MultiSessionEventsQuery(session_batch=batch)
runner = MultiSessionEventsQueryRunner(team=team, query=query)
response = runner.calculate()

# Process results
for session_events in response.session_events:
    session_id = session_events.session_id
    events = session_events.events
    # Process events for this session...
"""