"""
SessionBatchEventsQueryRunner extending EventsQueryRunner for multi-session event queries.

This runner leverages PostHog's existing EventsQueryRunner infrastructure while adding
session-specific capabilities like result grouping and per-session limiting.
"""

from typing import Any, List

from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from .schema import (
    SessionBatchEventsQuery,
    SessionBatchEventsQueryResponse,
    SessionEventsItem,
    SessionEventsResults,
)


class SessionBatchEventsQueryRunner(EventsQueryRunner):
    """
    Extended EventsQueryRunner for batch session event queries.
    
    This runner extends the standard EventsQueryRunner to handle multiple sessions
    efficiently while maintaining compatibility with all existing EventsQuery features.
    
    Key additions:
    1. Session-grouped result organization  
    2. Per-session event limiting
    3. Session-specific metadata tracking
    4. Optimized query construction for multi-session scenarios
    """
    
    query: SessionBatchEventsQuery
    response: SessionBatchEventsQueryResponse

    def calculate(self) -> SessionBatchEventsQueryResponse:
        """
        Execute the session batch query and organize results by session.
        
        This method leverages the parent EventsQueryRunner.calculate() for query execution,
        then post-processes the results to group by session and apply session-specific limits.
        
        Returns:
            SessionBatchEventsQueryResponse with session-grouped results and metadata
        """
        # Execute the base query using parent EventsQueryRunner
        base_response = super().calculate()
        
        # If group_by_session is False, return the base response as-is
        if not self.query.group_by_session:
            return SessionBatchEventsQueryResponse(
                **base_response.model_dump(),
                session_events=None,
                total_sessions=None,
            )
        
        # Group results by session and apply per-session limits
        session_events_data = self._group_events_by_session(
            results=base_response.results,
            columns=base_response.columns or []
        )
        
        # Create SessionEventsItem list
        session_events: List[SessionEventsItem] = []
        sessions_with_no_events: List[str] = []
        truncated_sessions: List[str] = []
        
        for session_id in self.query.session_ids:
            if session_id in session_events_data:
                events = session_events_data[session_id]
                
                # Apply per-session limit if specified
                truncated = False
                if self.query.limit_per_session and len(events) > self.query.limit_per_session:
                    events = events[:self.query.limit_per_session]
                    truncated = True
                    truncated_sessions.append(session_id)
                
                session_events.append(
                    SessionEventsItem(
                        session_id=session_id,
                        events=events,
                        event_count=len(events),
                        truncated=truncated,
                    )
                )
            else:
                sessions_with_no_events.append(session_id)
        
        # Calculate total events across all sessions (for potential future use)
        # total_events = sum(item.event_count for item in session_events)
        
        # Create the extended response
        return SessionBatchEventsQueryResponse(
            # Base EventsQueryResponse fields
            results=base_response.results,
            columns=base_response.columns,
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
            total_sessions=len(session_events),
            sessions_with_no_events=sessions_with_no_events,
            truncated_sessions=truncated_sessions,
        )

    def _group_events_by_session(
        self, 
        results: List[List[Any]], 
        columns: List[str]
    ) -> SessionEventsResults:
        """
        Group query results by session_id.
        
        Args:
            results: Raw query results from EventsQueryRunner
            columns: Column names for the query results
            
        Returns:
            Dictionary mapping session_id to list of events for that session
        """
        if not results or not columns:
            return {}
        
        # Find the index of the $session_id column
        session_id_index = None
        for i, col in enumerate(columns):
            if col in ["properties.$session_id", "$session_id"]:
                session_id_index = i
                break
        
        if session_id_index is None:
            # If no session_id column found, we can't group by session
            # This shouldn't happen if the query was constructed properly
            raise ValueError("No session_id column found in query results. Ensure 'properties.$session_id' is included in the select clause.")
        
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
            event_row = list(row[:session_id_index]) + list(row[session_id_index + 1:])
            events_by_session[session_id].append(event_row)
        
        return events_by_session

    def _get_session_id_column_index(self, columns: List[str]) -> int:
        """
        Find the index of the session_id column in the results.
        
        Args:
            columns: List of column names from the query
            
        Returns:
            Index of the session_id column
            
        Raises:
            ValueError: If session_id column is not found
        """
        session_id_columns = ["properties.$session_id", "$session_id"]
        
        for session_col in session_id_columns:
            try:
                return columns.index(session_col)
            except ValueError:
                continue
        
        raise ValueError(
            f"Session ID column not found in query results. "
            f"Expected one of {session_id_columns}, got columns: {columns}"
        )


# Convenience functions for common use cases

def query_session_events_batch(
    team,
    session_ids: List[str],
    after: str = "-7d",
    limit_per_session: int = 1000,
    max_total_events: int = 10000,
    events_to_ignore: List[str] = None,
    **kwargs
) -> SessionBatchEventsQueryResponse:
    """
    Convenience function to query events for multiple sessions with sensible defaults.
    
    Args:
        team: PostHog team instance
        session_ids: List of session IDs to query
        after: Time range start (e.g., "-7d", "2023-01-01")
        limit_per_session: Maximum events per session
        max_total_events: Maximum total events across all sessions
        events_to_ignore: Events to exclude from results
        **kwargs: Additional query parameters
        
    Returns:
        SessionBatchEventsQueryResponse with grouped session events
    """
    from .schema import create_session_batch_query
    
    query = create_session_batch_query(
        session_ids=session_ids,
        after=after,
        limit_per_session=limit_per_session,
        max_total_events=max_total_events,
        events_to_ignore=events_to_ignore,
        **kwargs
    )
    
    runner = SessionBatchEventsQueryRunner(team=team, query=query)
    return runner.calculate()


# Example usage for session summary workflows:
"""
# Simple batch query for session summaries
response = query_session_events_batch(
    team=team,
    session_ids=["session1", "session2", "session3"],
    after="-24h",
    limit_per_session=2000,
    max_total_events=8000
)

# Process grouped results
for session_item in response.session_events:
    session_id = session_item.session_id
    events = session_item.events
    print(f"Session {session_id}: {len(events)} events")
    
    # Process events for this session...
    for event_row in events:
        # event_row contains values in the order specified by response.columns
        pass

# Advanced usage with custom field selection
from .schema import create_session_batch_query

query = create_session_batch_query(
    session_ids=session_ids,
    select=["event", "timestamp", "properties.custom_field"],
    where=["properties.important = true"],
    after="-30d",
    limit_per_session=5000
)

runner = SessionBatchEventsQueryRunner(team=team, query=query)
response = runner.calculate()
"""