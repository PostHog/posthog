"""
Schema definitions for SessionBatchEventsQuery extending EventsQuery.

This approach leverages PostHog's existing EventsQuery infrastructure while adding
multi-session capabilities for session summary workflows.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ee.session_recordings.session_summary.input_data import EXTRA_SUMMARY_EVENT_FIELDS
from posthog.schema import (
    CachedEventsQueryResponse,
    EventsQuery,
    EventsQueryResponse,
)
from posthog.session_recordings.queries.session_replay_events import DEFAULT_EVENT_FIELDS


class SessionBatchEventsQuery(EventsQuery):
    """
    Extended EventsQuery for fetching events from multiple sessions efficiently.

    This extends the standard EventsQuery with session-specific capabilities:
    - Batch querying multiple sessions in a single request
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
        ..., description="List of session IDs to fetch events for. Will be translated to $session_id IN filter."
    )

    group_by_session: bool = Field(default=True, description="Whether to group results by session_id in the response")

    # Override response type to use our extended response
    response: Optional[SessionBatchEventsQueryResponse] = None


class SessionEventsItem(BaseModel):
    """
    Events from a single session within a batch query result.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., description="Session ID these events belong to")

    events: list[list[Any]] = Field(
        ...,
        description="List of events for this session, each event is a list of field values matching the query columns",
    )


class SessionBatchEventsQueryResponse(EventsQueryResponse):
    """Extended EventsQueryResponse for session batch queries."""

    model_config = ConfigDict(extra="forbid")

    # Session-grouped results (when group_by_session=True)
    session_events: Optional[list[SessionEventsItem]] = Field(
        default=None, description="Events grouped by session ID. Only populated when group_by_session=True."
    )

    sessions_with_no_events: list[str] = Field(
        default_factory=list, description="List of session IDs that had no matching events"
    )


class CachedSessionBatchEventsQueryResponse(CachedEventsQueryResponse):
    """Cached version of SessionBatchEventsQueryResponse."""

    model_config = ConfigDict(extra="forbid")

    session_events: Optional[list[SessionEventsItem]] = Field(
        default=None, description="Events grouped by session ID. Only populated when group_by_session=True."
    )
    sessions_with_no_events: list[str] = Field(
        default_factory=list, description="List of session IDs that had no matching events"
    )


# Type alias for convenience
SessionEventsResults = dict[str, list[list[Any]]]  # session_id -> events mapping


def create_session_batch_events_query(
    session_ids: list[str],
    select: Optional[list[str]] = None,
    events_to_ignore: Optional[list[str]] = None,
    after: Optional[str] = None,
    before: Optional[str] = None,
    max_total_events: Optional[int] = None,
    offset: Optional[int] = None,
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
