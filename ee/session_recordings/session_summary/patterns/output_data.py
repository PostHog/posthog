import dataclasses
import json
from pydantic import BaseModel, Field, ValidationError
from enum import Enum

import yaml

from ee.session_recordings.session_summary import SummaryValidationError
from ee.session_recordings.session_summary.output_data import SessionSummarySerializer
from ee.session_recordings.session_summary.summarize_session import SingleSessionSummaryLlmInputs
from ee.session_recordings.session_summary.utils import strip_raw_llm_content, unpack_full_event_id


class _SeverityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SessionGroupSummaryPattern(BaseModel):
    """Schema for validating individual pattern from LLM output"""

    pattern_id: int = Field(..., description="Unique identifier for the pattern", ge=1)
    pattern_name: str = Field(..., description="Human-readable name for the pattern", min_length=1)
    pattern_description: str = Field(..., description="Detailed description of the pattern", min_length=1)
    severity: _SeverityLevel = Field(..., description="Severity level of the pattern")
    indicators: list[str] = Field(..., description="List of indicators that signal this pattern", min_items=1)

    class Config:
        json_encoders = {_SeverityLevel: lambda v: v.value}


class SessionGroupSummaryPatternsList(BaseModel):
    """Schema for validating LLM output for patterns extraction"""

    patterns: list[SessionGroupSummaryPattern] = Field(..., description="List of patterns to validate", min_items=1)


class RawSessionGroupPatternAssignment(BaseModel):
    """Schema for validating individual pattern with events assigned from LLM output"""

    pattern_id: int = Field(..., description="Unique identifier for the pattern", ge=1)
    event_ids: list[str] = Field(..., description="List of event IDs assigned to this pattern", min_items=0)


class RawSessionGroupPatternAssignmentsList(BaseModel):
    """Schema for validating LLM output for patterns with events assigned"""

    patterns: list[RawSessionGroupPatternAssignment] = Field(
        ..., description="List of pattern assignments to validate", min_items=0
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class PaternAssignedEvent:
    """Event assigned to a pattern with actual ids attached. Dataclass, as not values validation is needed"""

    event_id: str
    event_uuid: str
    session_id: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class EnrichedPatternAssignedEvent(PaternAssignedEvent):
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
    event_type: str
    event_index: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class PatternAssignedEventSegmentContext:
    """Context for an event assigned to a pattern, to better understand the event in the context of the segment"""

    previous_events_in_segment: list[EnrichedPatternAssignedEvent]
    target_event: EnrichedPatternAssignedEvent
    next_events_in_segment: list[EnrichedPatternAssignedEvent]


def load_patterns_from_llm_content(raw_content: str, sessions_identifier: str) -> SessionGroupSummaryPatternsList:
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
        validated_patterns = SessionGroupSummaryPatternsList(**json_content)
    except ValidationError as err:
        raise SummaryValidationError(
            f"Error validating LLM output against the schema when extracting patterns for sessions {sessions_identifier}: {err}"
        ) from err
    return validated_patterns


def load_pattern_assignments_from_llm_content(
    raw_content: str, sessions_identifier: str
) -> RawSessionGroupPatternAssignmentsList:
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
    combined_event_ids_mapping: dict[str, str] = {}
    for session_input in single_session_summaries_inputs:
        combined_event_ids_mapping.update(session_input.event_ids_mapping)
    return combined_event_ids_mapping


def combine_patterns_assignments_from_single_session_summaries(
    patterns_assignments_list_of_lists: list[RawSessionGroupPatternAssignmentsList],
) -> dict[int, list[str]]:
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
    pattern_assigned_event: PaternAssignedEvent, event: dict
) -> EnrichedPatternAssignedEvent:
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


def _enrich_pattern_assigned_event_with_session_summary_data(
    pattern_assigned_event: PaternAssignedEvent,
    session_summaries: list[SessionSummarySerializer],
) -> PatternAssignedEventSegmentContext:
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
                    event_segment_context = PatternAssignedEventSegmentContext(
                        previous_events_in_segment=previous_events_in_segment,
                        target_event=current_event,
                        next_events_in_segment=next_events_in_segment,
                    )
                    return event_segment_context
                except Exception as err:
                    raise SummaryValidationError(
                        f"Error enriching pattern assigned event ({event}) with session summary data ({pattern_assigned_event})"
                    ) from err
    raise ValueError(f"Session summary with the required event ({pattern_assigned_event}) was not found")


def combine_patterns_with_events_context(
    combined_event_ids_mappings: dict[str, str],
    combined_patterns_assignments: dict[int, list[str]],
    session_summaries: list[SessionSummarySerializer],
) -> dict[int, list[PatternAssignedEventSegmentContext]]:
    pattern_event_ids_mapping: dict[int, list[PaternAssignedEvent]] = {}
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
            full_id_event = PaternAssignedEvent(event_id=event_id, event_uuid=event_uuid, session_id=session_id)
            event_segment_context = _enrich_pattern_assigned_event_with_session_summary_data(
                full_id_event, session_summaries
            )
            if pattern_id not in pattern_event_ids_mapping:
                pattern_event_ids_mapping[pattern_id] = []
            pattern_event_ids_mapping[pattern_id].append(event_segment_context)
    return pattern_event_ids_mapping


def load_session_summary_from_string(session_summary_str: str) -> SessionSummarySerializer:
    try:
        session_summary = SessionSummarySerializer(data=json.loads(session_summary_str))
        session_summary.is_valid(raise_exception=True)
        return session_summary
    except ValidationError as err:
        raise SummaryValidationError(
            f"Error validating session summary against the schema ({err}): {session_summary_str}"
        ) from err
