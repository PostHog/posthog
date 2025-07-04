"""
Schema definitions for SessionBatchEventsQuery extending EventsQuery.

This approach leverages PostHog's existing EventsQuery infrastructure while adding
multi-session capabilities for session summary workflows.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from posthog.schema import (
    EventsQuery,
    EventsQueryResponse,
)


class SessionBatchEventsQuery(EventsQuery):
    """
    Extended EventsQuery for fetching events from multiple sessions efficiently.
    
    This extends the standard EventsQuery with session-specific capabilities:
    - Batch querying multiple sessions in a single request
    - Per-session result limiting
    - Session-grouped result organization
    
    Inherits all EventsQuery functionality:
    - Standard field selection via `select`
    - Property filtering via `properties` and `fixedProperties`
    - Time filtering via `after` and `before`
    - HogQL filtering via `where`
    - Ordering via `orderBy`
    - Pagination via `limit` and `offset`
    """
    model_config = ConfigDict(extra="forbid")
    
    # Override kind to distinguish from base EventsQuery
    kind: Literal["SessionBatchEventsQuery"] = "SessionBatchEventsQuery"
    
    # Session-specific fields
    session_ids: list[str] = Field(
        ...,
        description="List of session IDs to fetch events for. Will be translated to $session_id IN filter."
    )
    
    group_by_session: bool = Field(
        default=True,
        description="Whether to group results by session_id in the response"
    )
    
    limit_per_session: Optional[int] = Field(
        default=None,
        description="Maximum number of events to return per session (applied after global ordering)"
    )
    
    # Override response type to use our extended response
    response: Optional[SessionBatchEventsQueryResponse] = None


class SessionEventsItem(BaseModel):
    """
    Container for events from a single session within a batch query result.
    """
    model_config = ConfigDict(extra="forbid")
    
    session_id: str = Field(
        ...,
        description="Session ID these events belong to"
    )
    
    events: list[list[Any]] = Field(
        ...,
        description="List of events for this session, each event is a list of field values matching the query columns"
    )
    
    event_count: int = Field(
        ...,
        description="Number of events returned for this session"
    )
    
    truncated: bool = Field(
        default=False,
        description="Whether the event list was truncated due to limit_per_session"
    )


class SessionBatchEventsQueryResponse(EventsQueryResponse):
    """
    Extended EventsQueryResponse for session batch queries.
    
    Maintains compatibility with standard EventsQueryResponse while adding
    session-specific result organization and metadata.
    """
    model_config = ConfigDict(extra="forbid")
    
    # Session-grouped results (when group_by_session=True)
    session_events: Optional[list[SessionEventsItem]] = Field(
        default=None,
        description="Events grouped by session ID. Only populated when group_by_session=True."
    )
    
    # Summary metrics for batch queries
    total_sessions: Optional[int] = Field(
        default=None,
        description="Total number of sessions that had events in the result"
    )
    
    sessions_with_no_events: list[str] = Field(
        default_factory=list,
        description="List of session IDs that had no matching events"
    )
    
    truncated_sessions: list[str] = Field(
        default_factory=list,
        description="List of session IDs that were truncated due to limit_per_session"
    )


# Type aliases for convenience
SessionEventsResults = dict[str, list[list[Any]]]  # session_id -> events mapping


def create_session_batch_query(
    session_ids: list[str],
    select: Optional[list[str]] = None,
    events_to_ignore: Optional[list[str]] = None,
    after: Optional[str] = None,
    before: Optional[str] = None,
    limit_per_session: Optional[int] = None,
    max_total_events: Optional[int] = None,
    include_session_id: bool = True,
    **kwargs: Any,
) -> SessionBatchEventsQuery:
    """
    Convenience function to create a SessionBatchEventsQuery with session summary defaults.
    
    Args:
        session_ids: List of session IDs to fetch events for
        select: Fields to select. Defaults to session summary fields if not provided
        events_to_ignore: List of event names to exclude from results
        after: Start time for event filtering
        before: End time for event filtering  
        limit_per_session: Maximum number of events per session
        max_total_events: Maximum total events across all sessions
        include_session_id: Whether to include $session_id in select fields
        **kwargs: Additional EventsQuery parameters
        
    Returns:
        SessionBatchEventsQuery: Configured query ready for execution
    """
    # Default field selection for session summaries
    if select is None:
        select = [
            "event",
            "timestamp", 
            "elements_chain_href",
            "elements_chain_texts",
            "elements_chain_elements",
            "properties.$window_id",
            "properties.$current_url",
            "properties.$event_type",
            # Additional fields typically needed for session summary analysis
            "elements_chain_ids",
            "elements_chain",
            "properties.$exception_types",
            "properties.$exception_sources", 
            "properties.$exception_values",
            "properties.$exception_fingerprint_record",
            "properties.$exception_functions",
            "uuid",
        ]
    
    # Ensure $session_id is included for grouping
    if include_session_id and "properties.$session_id" not in select:
        select.append("properties.$session_id")
    
    # Build WHERE clauses for session filtering and event exclusion
    where_clauses = []
    
    # Filter by session IDs
    where_clauses.append(f"properties.$session_id IN {session_ids}")
    
    # Exclude unwanted events (default to feature flag calls)
    if events_to_ignore is None:
        events_to_ignore = ["$feature_flag_called"]
    
    if events_to_ignore:
        event_list = "', '".join(events_to_ignore)
        where_clauses.append(f"event NOT IN ('{event_list}')")
    
    # Combine with any existing where clauses
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
        "limit_per_session": limit_per_session,
        "group_by_session": True,
        "after": after,
        "before": before,
        **kwargs,  # Allow overriding any defaults
    }
    
    return SessionBatchEventsQuery(**query_params)


# Example usage:
"""
# Create a batch query for multiple sessions
query = create_session_batch_query(
    session_ids=["session1", "session2", "session3"],
    after="-7d", 
    limit_per_session=1000,
    max_total_events=5000
)

# Execute with existing EventsQueryRunner infrastructure
from posthog.hogql_queries.events_query_runner import EventsQueryRunner

runner = SessionBatchEventsQueryRunner(team=team, query=query)
response = runner.calculate()

# Access grouped results
for session_item in response.session_events:
    session_id = session_item.session_id
    events = session_item.events
    print(f"Session {session_id}: {len(events)} events")
"""