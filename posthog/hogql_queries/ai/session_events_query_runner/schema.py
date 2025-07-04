"""
Schema definitions for MultiSessionEventsQuery and related types.

These schemas follow PostHog's standard query/response patterns and integrate
with the existing query infrastructure for session event fetching.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from posthog.schema import (
    DateRange,
    HogQLQueryModifiers,
    PropertyFilter,
    QueryLogTags,
    QueryStatus,
    QueryTiming,
)


class SessionEventsBatch(BaseModel):
    """
    Batch configuration for fetching events from multiple sessions.
    
    This model defines the input parameters for multi-session event queries,
    including session filtering, field selection, and performance limits.
    """
    model_config = ConfigDict(extra="forbid")
    
    session_ids: list[str] = Field(
        ..., 
        description="List of session IDs to fetch events for"
    )
    
    # Time range filtering (optional, derived from session metadata if not provided)
    date_range: Optional[DateRange] = Field(
        default=None,
        description="Optional date range to filter events. If not provided, will be derived from session metadata."
    )
    
    # Event filtering
    events_to_ignore: Optional[list[str]] = Field(
        default=None,
        description="List of event names to exclude from results (e.g., '$feature_flag_called')"
    )
    
    properties: Optional[list[PropertyFilter]] = Field(
        default=None,
        description="Property filters to apply to events"
    )
    
    # Field selection
    extra_fields: Optional[list[str]] = Field(
        default=None,
        description="Additional fields to include beyond the default event fields"
    )
    
    # Performance controls
    limit_per_session: Optional[int] = Field(
        default=None,
        description="Maximum number of events to return per session"
    )
    
    max_total_events: Optional[int] = Field(
        default=None,
        description="Maximum total events across all sessions to prevent memory issues"
    )
    
    # Processing options
    include_session_metadata: bool = Field(
        default=True,
        description="Whether to include session metadata in the response"
    )


class MultiSessionEventsQuery(BaseModel):
    """
    Query definition for fetching events from multiple sessions in a single optimized query.
    
    This query type is designed for session summary workflows where events from
    multiple sessions need to be fetched efficiently.
    """
    model_config = ConfigDict(extra="forbid")
    
    # Standard query fields following PostHog patterns
    kind: Literal["MultiSessionEventsQuery"] = "MultiSessionEventsQuery"
    
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None,
        description="Modifiers used when performing the query"
    )
    
    response: Optional[MultiSessionEventsQueryResponse] = None
    
    tags: Optional[QueryLogTags] = None
    
    version: Optional[float] = Field(
        default=None,
        description="Version of the query schema, used for migrations"
    )
    
    # Query-specific configuration
    session_batch: SessionEventsBatch = Field(
        ...,
        description="Batch configuration for the multi-session events query"
    )
    
    # Standard filtering options
    filter_test_accounts: Optional[bool] = Field(
        default=None,
        description="Filter test accounts from results"
    )


class MultiSessionEventsItem(BaseModel):
    """
    Container for events from a single session within a multi-session query result.
    """
    model_config = ConfigDict(extra="forbid")
    
    session_id: str = Field(
        ...,
        description="Session ID these events belong to"
    )
    
    events: list[list[Any]] = Field(
        ...,
        description="List of events for this session, each event is a list of field values"
    )
    
    event_count: int = Field(
        ...,
        description="Number of events returned for this session"
    )
    
    # Optional metadata
    session_metadata: Optional[dict[str, Any]] = Field(
        default=None,
        description="Session metadata if requested in the query"
    )
    
    truncated: bool = Field(
        default=False,
        description="Whether the event list was truncated due to limits"
    )


class MultiSessionEventsQueryResponse(BaseModel):
    """
    Response from a MultiSessionEventsQuery containing events grouped by session.
    
    Follows PostHog's standard query response pattern with results, metadata,
    and execution information.
    """
    model_config = ConfigDict(extra="forbid")
    
    # Core results
    session_events: list[MultiSessionEventsItem] = Field(
        ...,
        description="Events grouped by session ID"
    )
    
    columns: list[str] = Field(
        ...,
        description="Column names for the event data in consistent order"
    )
    
    types: Optional[list[str]] = Field(
        default=None,
        description="Data types for each column"
    )
    
    # Summary metrics
    total_sessions: int = Field(
        ...,
        description="Total number of sessions with events in the response"
    )
    
    total_events: int = Field(
        ...,
        description="Total number of events across all sessions"
    )
    
    # Query execution metadata (standard PostHog fields)
    hogql: str = Field(
        ...,
        description="Generated HogQL query that was executed"
    )
    
    timings: Optional[list[QueryTiming]] = Field(
        default=None,
        description="Measured timings for different parts of the query generation process"
    )
    
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None,
        description="Modifiers used when performing the query"
    )
    
    # Error handling
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."
    )
    
    # Pagination and status
    hasMore: Optional[bool] = Field(
        default=None,
        description="Whether there are more results available"
    )
    
    limit: Optional[int] = Field(
        default=None,
        description="Limit applied to the query"
    )
    
    offset: Optional[int] = Field(
        default=None,
        description="Offset applied to the query"
    )
    
    query_status: Optional[QueryStatus] = Field(
        default=None,
        description="Query status indicates whether next to the provided data, a query is still running."
    )
    
    # Performance metrics
    sessions_with_no_events: list[str] = Field(
        default_factory=list,
        description="List of session IDs that had no events"
    )
    
    truncated_sessions: list[str] = Field(
        default_factory=list,
        description="List of session IDs that were truncated due to limits"
    )


class CachedMultiSessionEventsQueryResponse(MultiSessionEventsQueryResponse):
    """
    Cached version of MultiSessionEventsQueryResponse with cache metadata.
    
    Extends the base response with caching information following PostHog's
    cached response pattern.
    """
    model_config = ConfigDict(extra="forbid")
    
    # Caching metadata
    cache_key: str = Field(
        ...,
        description="Cache key used for this query result"
    )
    
    cache_target_age: Optional[datetime] = Field(
        default=None,
        description="Target age for cache invalidation"
    )
    
    calculation_trigger: Optional[str] = Field(
        default=None,
        description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    
    is_cached: bool = Field(
        ...,
        description="Whether this result was served from cache"
    )
    
    last_refresh: datetime = Field(
        ...,
        description="When this cache entry was last refreshed"
    )
    
    next_allowed_client_refresh: datetime = Field(
        ...,
        description="When the client is next allowed to refresh this query"
    )
    
    timezone: str = Field(
        ...,
        description="Timezone used for the query execution"
    )


# Type aliases for convenience
SessionEventsResults = dict[str, list[list[Any]]]  # session_id -> events mapping
SessionMetadataDict = dict[str, dict[str, Any]]    # session_id -> metadata mapping