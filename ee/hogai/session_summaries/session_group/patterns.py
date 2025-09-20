import dataclasses
from enum import Enum
from math import floor
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError, field_serializer, field_validator
from temporalio.exceptions import ApplicationError

from ee.hogai.session_summaries import SummaryValidationError
from ee.hogai.session_summaries.constants import FAILED_PATTERNS_ENRICHMENT_MIN_RATIO
from ee.hogai.session_summaries.session.output_data import SessionSummarySerializer
from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs
from ee.hogai.session_summaries.utils import logging_session_ids
from ee.hogai.utils.yaml import load_yaml_from_raw_llm_content

logger = structlog.get_logger(__name__)


class _SeverityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclasses.dataclass(frozen=True, kw_only=True)
class PatternAssignedEvent:
    """Event assigned to a pattern with actual ids attached. Dataclass, as not values validation is needed"""

    event_id: str
    event_uuid: str
    session_id: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class EnrichedPatternAssignedEvent(PatternAssignedEvent):
    """Event assigned to a pattern enriched with session summary data"""

    description: str
    abandonment: bool
    confusion: bool
    exception: str | None
    timestamp: str
    milliseconds_since_start: int
    window_id: str | None
    current_url: str | None
    event: str
    event_type: str | None
    event_index: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class PatternAssignedEventSegmentContext:
    """Context for an event assigned to a pattern, to better understand the event in the context of the segment"""

    segment_name: str
    segment_outcome: str
    segment_success: bool
    segment_index: int
    previous_events_in_segment: list[EnrichedPatternAssignedEvent]
    target_event: EnrichedPatternAssignedEvent
    next_events_in_segment: list[EnrichedPatternAssignedEvent]


class RawSessionGroupSummaryPattern(BaseModel):
    """Schema for validating individual pattern from LLM output"""

    pattern_id: int = Field(..., description="Unique identifier for the pattern", ge=1)
    pattern_name: str = Field(..., description="Human-readable name for the pattern", min_length=1)
    pattern_description: str = Field(..., description="Detailed description of the pattern", min_length=1)
    severity: _SeverityLevel = Field(..., description="Severity level of the pattern")
    indicators: list[str] = Field(..., description="List of indicators that signal this pattern", min_length=1)

    @field_serializer("severity")
    def serialize_severity(self, severity: _SeverityLevel) -> str:
        """Convert enum to string value for JSON serialization"""
        return severity.value


class EnrichedSessionGroupSummaryPatternStats(BaseModel):
    """How many pattern occurrences, how pattern affected the success rate of segments, and similar"""

    occurences: int = Field(..., description="How many times the pattern occurred")
    sessions_affected: int = Field(..., description="How many sessions were affected by the pattern")
    sessions_affected_ratio: float = Field(
        ...,
        description="How many sessions were affected by the pattern (ratio of sessions affected to total sessions)",
        ge=0.0,
        le=1.0,
    )
    segments_success_ratio: float = Field(
        ..., description="How many segments with noticed pattern were successful", ge=0.0, le=1.0
    )


class EnrichedSessionGroupSummaryPattern(RawSessionGroupSummaryPattern):
    """Enriched pattern with events context"""

    events: list[PatternAssignedEventSegmentContext] = Field(
        ..., description="List of events assigned to the pattern", min_length=0
    )
    stats: EnrichedSessionGroupSummaryPatternStats = Field(..., description="Calculated stats for the pattern")

    @field_serializer("events")
    def serialize_events(self, events: list[PatternAssignedEventSegmentContext]) -> list[dict]:
        """Convert dataclass events to dicts for JSON serialization"""
        return [dataclasses.asdict(event) for event in events]


class RawSessionGroupSummaryPatternsList(BaseModel):
    """Schema for validating LLM output for patterns extraction"""

    patterns: list[RawSessionGroupSummaryPattern] = Field(..., description="List of patterns to validate", min_length=0)


class EnrichedSessionGroupSummaryPatternsList(BaseModel):
    """Enriched patterns with events context ready to be displayed in UI"""

    patterns: list[EnrichedSessionGroupSummaryPattern] = Field(
        ..., description="List of patterns with events context", min_length=0
    )


class RawSessionGroupPatternAssignment(BaseModel):
    """Schema for validating individual pattern with events assigned from LLM output"""

    pattern_id: int = Field(..., description="Unique identifier for the pattern", ge=1)
    event_ids: list[str] = Field(..., description="List of event IDs assigned to this pattern", min_length=0)

    @field_validator("event_ids", mode="before")
    @classmethod
    def stringify_event_ids(cls, v: list[str | int]) -> list[str]:
        """If event ids are valid ints, LLM sometimes returns them as ints, so we need to convert them to strings"""
        try:
            return [str(item) for item in v]
        except Exception as err:
            raise SummaryValidationError(
                f"Error converting event ids to strings when validating pattern assignments ({v}): {err}"
            ) from err


class RawSessionGroupPatternAssignmentsList(BaseModel):
    """Schema for validating LLM output for patterns with events assigned"""

    patterns: list[RawSessionGroupPatternAssignment] = Field(
        ..., description="List of pattern assignments to validate", min_length=0
    )


def load_patterns_from_llm_content(raw_content: str, sessions_identifier: str) -> RawSessionGroupSummaryPatternsList:
    """Parse YAML LLM output and validate extracted patterns."""
    if not raw_content:
        raise SummaryValidationError(
            f"No LLM content found when extracting patterns for sessions {sessions_identifier}"
        )
    try:
        # Patterns aren't streamed, so the initial state is the final one
        json_content = load_yaml_from_raw_llm_content(raw_content=raw_content, final_validation=True)
        if not isinstance(json_content, dict):
            raise Exception(f"LLM output is not a dictionary: {raw_content}")
    except Exception as err:
        raise SummaryValidationError(
            f"Error loading YAML content into JSON when extracting patterns for sessions {sessions_identifier}: {err}"
        ) from err
    # Validate the LLM output against the schema
    try:
        validated_patterns = RawSessionGroupSummaryPatternsList(**json_content)
    except ValidationError as err:
        raise SummaryValidationError(
            f"Error validating LLM output against the schema when extracting patterns for sessions {sessions_identifier}: {err}"
        ) from err
    return validated_patterns


def load_pattern_assignments_from_llm_content(
    raw_content: str, sessions_identifier: str
) -> RawSessionGroupPatternAssignmentsList:
    """Parse YAML output and validate pattern assignments."""
    if not raw_content:
        raise SummaryValidationError(
            f"No LLM content found when extracting pattern assignments for sessions {sessions_identifier}"
        )
    try:
        # Patterns aren't streamed, so the initial state is the final one
        json_content = load_yaml_from_raw_llm_content(raw_content=raw_content, final_validation=True)
        if not isinstance(json_content, dict):
            raise Exception(f"LLM output is not a dictionary: {raw_content}")
    except Exception as err:
        raise SummaryValidationError(
            f"Error loading YAML content into JSON when extracting pattern assignments for sessions {sessions_identifier}: {err}"
        ) from err
    # Validate the LLM output against the schema
    try:
        validated_assignments = RawSessionGroupPatternAssignmentsList(**json_content)
    except ValidationError as err:
        raise SummaryValidationError(
            f"Error validating LLM output against the schema when extracting pattern assignments for sessions {sessions_identifier}: {err}"
        ) from err
    return validated_assignments


def create_event_ids_mapping_from_ready_summaries(
    session_summaries: list[SessionSummarySerializer],
) -> dict[str, tuple[str, str]]:
    """Create event_id to (event_uuid, session_id) tuple mapping from ready summaries"""
    combined_event_ids_mapping: dict[str, tuple[str, str]] = {}
    for summary in session_summaries:
        if "key_actions" not in summary.data:
            continue
        # Extract mappings from key_actions
        for segment_actions in summary.data["key_actions"]:
            if "events" not in segment_actions:
                continue
            # Assuming that all the summaries are unique, so a single event could be only in one summary
            for event in segment_actions["events"]:
                # Add mapping if both event_id and event_uuid exist
                if not event.get("event_id") or not event.get("event_uuid") or not event.get("session_id"):
                    continue
                combined_event_ids_mapping[event["event_id"]] = str(event["event_uuid"]), str(event["session_id"])
    return combined_event_ids_mapping


def combine_event_ids_mappings_from_single_session_summaries(
    single_session_summaries_inputs: list[SingleSessionSummaryLlmInputs],
) -> dict[str, str]:
    """Merge event ID mappings from all session inputs."""
    combined_event_ids_mapping: dict[str, str] = {}
    for session_input in single_session_summaries_inputs:
        combined_event_ids_mapping.update(session_input.event_ids_mapping)
    return combined_event_ids_mapping


def combine_patterns_assignments_from_single_session_summaries(
    patterns_assignments_list_of_lists: list[RawSessionGroupPatternAssignmentsList],
) -> dict[int, list[str]]:
    """Merge pattern assignments from multiple sessions."""
    combined_patterns_assignments: dict[int, list[str]] = {}
    for assignments_list in patterns_assignments_list_of_lists:
        for pattern_assignment in assignments_list.patterns:
            pattern_id = pattern_assignment.pattern_id
            event_ids = pattern_assignment.event_ids
            if pattern_id not in combined_patterns_assignments:
                combined_patterns_assignments[pattern_id] = []
            combined_patterns_assignments[pattern_id].extend(event_ids)
    return combined_patterns_assignments


def _enriched_event_from_session_summary_event(
    pattern_assigned_event: PatternAssignedEvent, event: dict
) -> EnrichedPatternAssignedEvent:
    """Build an enriched event from summary event data."""
    enriched_event = EnrichedPatternAssignedEvent(
        event_id=pattern_assigned_event.event_id,
        event_uuid=pattern_assigned_event.event_uuid,
        session_id=pattern_assigned_event.session_id,
        description=event["description"],
        abandonment=event["abandonment"],
        confusion=event["confusion"],
        exception=event["exception"],
        timestamp=event["timestamp"],
        milliseconds_since_start=event["milliseconds_since_start"],
        window_id=event["window_id"],
        current_url=event["current_url"],
        event=event["event"],
        event_type=event["event_type"],
        event_index=event["event_index"],
    )
    return enriched_event


def _get_segment_name_and_outcome_from_session_summary(
    target_segment_index: int, session_summary: SessionSummarySerializer
) -> tuple[str, str, bool]:
    """Return segment name and outcome for a given index."""
    segment_name = segment_outcome = segment_success = None
    for segment_state in session_summary.data["segments"]:
        if str(segment_state["index"]) != str(target_segment_index):
            continue
        segment_name = segment_state["name"]
        break
    for segment_outcome_state in session_summary.data["segment_outcomes"]:
        if str(segment_outcome_state["segment_index"]) != str(target_segment_index):
            continue
        segment_outcome = segment_outcome_state["summary"]
        segment_success = segment_outcome_state["success"]
        break
    if segment_name is None or segment_outcome is None or segment_success is None:
        raise ValueError(
            f"Segment name, outcome or success not found for segment index {target_segment_index} in session summary: {session_summary.data}"
        )
    return segment_name, segment_outcome, segment_success


def _enrich_pattern_assigned_event_with_session_summary_data(
    pattern_assigned_event: PatternAssignedEvent,
    session_summaries: list[SessionSummarySerializer],
) -> PatternAssignedEventSegmentContext:
    """Attach session summary context to a pattern-assigned event."""
    for session_summary in session_summaries:
        key_actions = session_summary.data["key_actions"]
        for segment_key_actions in key_actions:
            for event_index, event in enumerate(segment_key_actions["events"]):
                # Find the event in the session summary
                if event["event_id"] != pattern_assigned_event.event_id:
                    continue
                try:
                    # If the event is found, enrich it with session summary data first
                    current_event = _enriched_event_from_session_summary_event(pattern_assigned_event, event)
                    events_in_segment = segment_key_actions["events"]
                    events_in_segment_count = len(events_in_segment)
                    # Find and enrich previous events
                    if event_index == 0:
                        # If the captured event is the first in the segment, there are no previous events
                        previous_events_in_segment = []
                    else:
                        # TODO: Move 3 to a constant
                        previous_events_in_segment = [
                            _enriched_event_from_session_summary_event(pattern_assigned_event, previous_event)
                            for previous_event in events_in_segment[max(0, event_index - 3) : event_index]
                        ]
                    # Find and enrich next events
                    if event_index == events_in_segment_count - 1:
                        # If the captured event is the last in the segment, there are no next events
                        next_events_in_segment = []
                    else:
                        next_events_in_segment = [
                            _enriched_event_from_session_summary_event(pattern_assigned_event, next_event)
                            for next_event in events_in_segment[event_index + 1 : event_index + 4]
                        ]
                    segment_index = segment_key_actions["segment_index"]
                    segment_name, segment_outcome, segment_success = _get_segment_name_and_outcome_from_session_summary(
                        target_segment_index=segment_index, session_summary=session_summary
                    )
                    event_segment_context = PatternAssignedEventSegmentContext(
                        previous_events_in_segment=previous_events_in_segment,
                        target_event=current_event,
                        next_events_in_segment=next_events_in_segment,
                        segment_name=segment_name,
                        segment_outcome=segment_outcome,
                        segment_success=segment_success,
                        segment_index=segment_index,
                    )
                    return event_segment_context
                except Exception as err:
                    raise SummaryValidationError(
                        f"Error enriching pattern assigned event ({event}) with session summary data ({pattern_assigned_event}): {err}"
                    ) from err
    raise ValueError(f"Session summary with the required event ({pattern_assigned_event}) was not found")


def combine_patterns_ids_with_events_context(
    combined_event_ids_mappings: dict[str, tuple[str, str]],
    combined_patterns_assignments: dict[int, list[str]],
    session_summaries: list[SessionSummarySerializer],
) -> dict[int, list[PatternAssignedEventSegmentContext]]:
    """Map pattern IDs to enriched event contexts using assignments context."""
    pattern_event_ids_mapping: dict[int, list[PatternAssignedEventSegmentContext]] = {}
    patterns_with_removed_non_blocking_exceptions = set()
    # Iterate over patterns to which we assigned event ids
    for pattern_id, event_ids in combined_patterns_assignments.items():
        for event_id in event_ids:
            # Find full session id and event uuid for the event id
            ids_tuple = combined_event_ids_mappings.get(event_id)
            if not ids_tuple:
                logger.exception(
                    f"Event uuid and session id not found for event_id {event_id} when combining patterns with event ids "
                    f"for pattern_id {pattern_id}"
                )
                # Skip the event
                continue
            event_uuid, session_id = ids_tuple
            pattern_assigned_event = PatternAssignedEvent(
                event_id=event_id, event_uuid=event_uuid, session_id=session_id
            )
            event_segment_context = _enrich_pattern_assigned_event_with_session_summary_data(
                pattern_assigned_event, session_summaries
            )
            # Skip non-blocking exceptions, allow blocking ones and abandonment (no exception)
            if event_segment_context.target_event.exception == "non-blocking":
                patterns_with_removed_non_blocking_exceptions.add(pattern_id)
                continue
            if pattern_id not in pattern_event_ids_mapping:
                pattern_event_ids_mapping[pattern_id] = []
            pattern_event_ids_mapping[pattern_id].append(event_segment_context)
    # If we removed all non-blocking exceptions for some patterns - it's not a failure
    for pattern_id in patterns_with_removed_non_blocking_exceptions:
        if pattern_id in pattern_event_ids_mapping:
            # Avoid touching patterns that have events left even after removing non-blocking exceptions
            continue
        # Let's back the patterns we emptied, so we can properly calculate failure ratio
        pattern_event_ids_mapping[pattern_id] = []
    return pattern_event_ids_mapping


def _calculate_pattern_stats(
    pattern_events: list[PatternAssignedEventSegmentContext], total_sessions_count: int
) -> EnrichedSessionGroupSummaryPatternStats:
    """Compute aggregate stats for a pattern based on assigned events."""
    # First, let calculate how occurences and sessions affected are calculated
    occurences = len(pattern_events)
    sessions_affected = len({event.target_event.session_id for event in pattern_events})
    sessions_affected_ratio = round(sessions_affected / total_sessions_count, 2)
    # Next, let's calculate how the pattern affected the success rate of segments
    # Keep only unique segments within pattern to avoid false stats
    unique_segments: dict[str, PatternAssignedEventSegmentContext] = {}
    for event in pattern_events:
        segment_identifier = f"{event.target_event.session_id}_{event.segment_index}"
        unique_segments[segment_identifier] = event
    segments_count = len(unique_segments)
    positive_outcomes = len([event for event in unique_segments.values() if event.segment_success is True])
    segments_success_ratio = round(positive_outcomes / segments_count, 2) if segments_count > 0 else 0
    return EnrichedSessionGroupSummaryPatternStats(
        occurences=occurences,
        sessions_affected=sessions_affected,
        sessions_affected_ratio=sessions_affected_ratio,
        segments_success_ratio=segments_success_ratio,
    )


def combine_patterns_with_events_context(
    patterns: RawSessionGroupSummaryPatternsList,
    pattern_id_to_event_context_mapping: dict[int, list[PatternAssignedEventSegmentContext]],
    session_ids: list[str],
    user_id: int,
) -> EnrichedSessionGroupSummaryPatternsList:
    """Attach event context and stats to each extracted pattern."""
    combined_patterns = []
    non_failed_empty_patterns_count = 0
    for pattern in patterns.patterns:
        pattern_id = pattern.pattern_id
        pattern_events = pattern_id_to_event_context_mapping.get(int(pattern_id))
        if not pattern_events:
            if pattern_events is not None:
                # If the pattern has not events, but is in the mapping - it's not a failure,
                # it means we made it empty by removing non-blocking exceptions
                non_failed_empty_patterns_count += 1
            continue
        enriched_pattern = EnrichedSessionGroupSummaryPattern(
            **pattern.model_dump(),
            events=pattern_events,
            stats=_calculate_pattern_stats(pattern_events, len(session_ids)),
        )
        combined_patterns.append(enriched_pattern)
    # If not enough patterns were properly enriched - fail the activity
    # Using `floor` as for small numbers of patterns - >30% could be filtered as "non-blocking only"
    minimum_expected_patterns_count = max(1, floor(len(patterns.patterns) * FAILED_PATTERNS_ENRICHMENT_MIN_RATIO))
    successful_patterns_count = len(combined_patterns) + non_failed_empty_patterns_count
    failed_patterns_count = len(patterns.patterns) - successful_patterns_count
    if minimum_expected_patterns_count > successful_patterns_count:
        exception_message = (
            f"Too many patterns failed to enrich with session meta, when summarizing {len(session_ids)} "
            f"sessions ({logging_session_ids(session_ids)}) for user {user_id}. "
            f"Input: {len(patterns.patterns)}; success: {successful_patterns_count} "
            f"(enriched: {len(combined_patterns)}); failure: {failed_patterns_count}"
        )
        logger.exception(exception_message)
        raise ApplicationError(exception_message)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    combined_patterns.sort(key=lambda p: severity_order.get(p.severity.value, 3))
    return EnrichedSessionGroupSummaryPatternsList(patterns=combined_patterns)


def session_summary_to_serializer(session_summary_dict: dict[str, Any]) -> SessionSummarySerializer:
    """Validate and create a serializer from a session summary dict."""
    try:
        session_summary = SessionSummarySerializer(data=session_summary_dict)
        session_summary.is_valid(raise_exception=True)
        return session_summary
    except ValidationError as err:
        raise SummaryValidationError(
            f"Error validating session summary against the schema ({err}): {session_summary_dict}"
        ) from err
