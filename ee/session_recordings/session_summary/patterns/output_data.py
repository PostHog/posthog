import dataclasses
import json
from pydantic import BaseModel, Field, ValidationError, field_serializer, field_validator
from enum import Enum

import yaml
import structlog
from ee.session_recordings.session_summary import SummaryValidationError
from ee.session_recordings.session_summary.output_data import SessionSummarySerializer
from ee.session_recordings.session_summary.summarize_session import SingleSessionSummaryLlmInputs
from ee.session_recordings.session_summary.utils import strip_raw_llm_content, unpack_full_event_id

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
    window_id: str
    current_url: str
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

    patterns: list[RawSessionGroupSummaryPattern] = Field(..., description="List of patterns to validate", min_length=1)


class EnrichedSessionGroupSummaryPatternsList(BaseModel):
    """Enriched patterns with events context ready to be displayed in UI"""

    patterns: list[EnrichedSessionGroupSummaryPattern] = Field(
        ..., description="List of patterns with events context", min_length=1
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
        json_content: dict = yaml.safe_load(strip_raw_llm_content(raw_content))
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
        json_content: dict = yaml.safe_load(strip_raw_llm_content(raw_content))
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
    combined_event_ids_mappings: dict[str, str],
    combined_patterns_assignments: dict[int, list[str]],
    session_summaries: list[SessionSummarySerializer],
) -> dict[int, list[PatternAssignedEventSegmentContext]]:
    """Map pattern IDs to enriched event contexts using assignments context."""
    pattern_event_ids_mapping: dict[int, list[PatternAssignedEventSegmentContext]] = {}
    # Iterate over patterns to which we assigned event ids
    for pattern_id, event_ids in combined_patterns_assignments.items():
        for event_id in event_ids:
            # Find full session id and event uuid for the event id
            full_event_id = combined_event_ids_mappings.get(event_id)
            if not full_event_id:
                raise ValueError(
                    f"Full event ID not found for event_id {event_id} when combining patterns with event ids "
                    f"for pattern_id {pattern_id}:\n{combined_patterns_assignments}\n{combined_event_ids_mappings}"
                )
            # Map them to the pattern id to be able to enrich summaries and calculate patterns stats
            session_id, event_uuid = unpack_full_event_id(full_event_id)
            full_id_event = PatternAssignedEvent(event_id=event_id, event_uuid=event_uuid, session_id=session_id)
            event_segment_context = _enrich_pattern_assigned_event_with_session_summary_data(
                full_id_event, session_summaries
            )
            if pattern_id not in pattern_event_ids_mapping:
                pattern_event_ids_mapping[pattern_id] = []
            pattern_event_ids_mapping[pattern_id].append(event_segment_context)
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
    total_sessions_count: int,
) -> EnrichedSessionGroupSummaryPatternsList:
    """Attach event context and stats to each extracted pattern."""
    combined_patterns = []
    for pattern in patterns.patterns:
        pattern_id = pattern.pattern_id
        pattern_events = pattern_id_to_event_context_mapping.get(int(pattern_id), [])
        if not pattern_events:
            logger.warning(
                f"No events found for pattern {pattern_id} when combining patterns with events context: {pattern_id_to_event_context_mapping}"
            )
        enriched_pattern = EnrichedSessionGroupSummaryPattern(
            **pattern.model_dump(),
            events=pattern_events,
            stats=_calculate_pattern_stats(pattern_events, total_sessions_count),
        )
        combined_patterns.append(enriched_pattern)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    combined_patterns.sort(key=lambda p: severity_order.get(p.severity.value, 3))
    return EnrichedSessionGroupSummaryPatternsList(patterns=combined_patterns)


def load_session_summary_from_string(session_summary_str: str) -> SessionSummarySerializer:
    """Deserialize a stored session summary JSON string."""
    try:
        session_summary = SessionSummarySerializer(data=json.loads(session_summary_str))
        session_summary.is_valid(raise_exception=True)
        return session_summary
    except ValidationError as err:
        raise SummaryValidationError(
            f"Error validating session summary against the schema ({err}): {session_summary_str}"
        ) from err
