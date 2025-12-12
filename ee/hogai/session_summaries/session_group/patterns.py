import dataclasses
from enum import Enum
from math import floor
from typing import Any

from django.db.models import Prefetch

import structlog
from pydantic import BaseModel, Field, ValidationError, field_serializer, field_validator
from temporalio.exceptions import ApplicationError

from posthog.models.person import Person, PersonDistinctId
from posthog.models.person.util import get_persons_by_distinct_ids

from ee.hogai.session_summaries import SummaryValidationError
from ee.hogai.session_summaries.constants import FAILED_PATTERNS_ENRICHMENT_MIN_RATIO
from ee.hogai.session_summaries.session.output_data import SessionSummaryIssueTypes, SessionSummarySerializer
from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs
from ee.hogai.session_summaries.utils import logging_session_ids
from ee.hogai.utils.yaml import load_yaml_from_raw_llm_content
from ee.models.session_summaries import SingleSessionSummary

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
    session_start_time_str: str | None
    session_duration: int | None
    person_distinct_ids: list[str]
    person_email: str | None


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
            msg = f"Error converting event ids to strings when validating pattern assignments ({v}): {err}"
            logger.exception(msg, signals_type="session-summaries")
            raise SummaryValidationError(msg) from err


class RawSessionGroupPatternAssignmentsList(BaseModel):
    """Schema for validating LLM output for patterns with events assigned"""

    patterns: list[RawSessionGroupPatternAssignment] = Field(
        ..., description="List of pattern assignments to validate", min_length=0
    )


def load_patterns_from_llm_content(raw_content: str, sessions_identifier: str) -> RawSessionGroupSummaryPatternsList:
    """Parse YAML LLM output and validate extracted patterns."""
    if not raw_content:
        msg = f"No LLM content found when extracting patterns for sessions {sessions_identifier}"
        logger.error(msg, signals_type="session-summaries")
        raise SummaryValidationError(msg)
    try:
        # Patterns aren't streamed, so the initial state is the final one
        json_content = load_yaml_from_raw_llm_content(raw_content=raw_content, final_validation=True)
        if not isinstance(json_content, dict):
            raise Exception(f"LLM output is not a dictionary: {raw_content}")
    except Exception as err:
        msg = f"Error loading YAML content into JSON when extracting patterns for sessions {sessions_identifier}: {err}"
        logger.exception(msg, signals_type="session-summaries")
        raise SummaryValidationError(msg) from err
    # Validate the LLM output against the schema
    try:
        validated_patterns = RawSessionGroupSummaryPatternsList(**json_content)
    except ValidationError as err:
        msg = f"Error validating LLM output against the schema when extracting patterns for sessions {sessions_identifier}: {err}"
        logger.exception(msg, signals_type="session-summaries")
        raise SummaryValidationError(msg) from err
    return validated_patterns


def load_pattern_assignments_from_llm_content(
    raw_content: str, sessions_identifier: str
) -> RawSessionGroupPatternAssignmentsList:
    """Parse YAML output and validate pattern assignments."""
    if not raw_content:
        msg = f"No LLM content found when extracting pattern assignments for sessions {sessions_identifier}"
        logger.error(msg, signals_type="session-summaries")
        raise SummaryValidationError(msg)
    try:
        # Patterns aren't streamed, so the initial state is the final one
        json_content = load_yaml_from_raw_llm_content(raw_content=raw_content, final_validation=True)
        if not isinstance(json_content, dict):
            raise Exception(f"LLM output is not a dictionary: {raw_content}")
    except Exception as err:
        msg = f"Error loading YAML content into JSON when extracting pattern assignments for sessions {sessions_identifier}: {err}"
        logger.exception(msg, signals_type="session-summaries")
        raise SummaryValidationError(msg) from err
    # Validate the LLM output against the schema
    try:
        validated_assignments = RawSessionGroupPatternAssignmentsList(**json_content)
    except ValidationError as err:
        msg = f"Error validating LLM output against the schema when extracting pattern assignments for sessions {sessions_identifier}: {err}"
        logger.exception(msg, signals_type="session-summaries")
        raise SummaryValidationError(msg) from err
    return validated_assignments


def create_event_ids_mapping_from_ready_summaries(
    session_id_to_ready_summaries_mapping: dict[str, SingleSessionSummary],
) -> dict[str, tuple[str, str]]:
    """Create event_id to (event_uuid, session_id) tuple mapping from ready summaries"""
    combined_event_ids_mapping: dict[str, tuple[str, str]] = {}
    for db_summary in session_id_to_ready_summaries_mapping.values():
        summary = session_summary_to_serializer(db_summary.summary)
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
    event_id_to_session_id_mapping: dict[str, tuple[str, str]],
) -> dict[int, list[str]]:
    """Merge pattern assignments from multiple sessions.

    Deduplicates to keep only one event per session per pattern (first occurrence wins).
    """
    combined_patterns_assignments: dict[int, list[str]] = {}
    # Track which sessions have already contributed to each pattern
    pattern_session_seen: dict[int, set[str]] = {}
    for assignments_list in patterns_assignments_list_of_lists:
        for pattern_assignment in assignments_list.patterns:
            pattern_id = pattern_assignment.pattern_id
            if pattern_id not in combined_patterns_assignments:
                combined_patterns_assignments[pattern_id] = []
                pattern_session_seen[pattern_id] = set()
            for event_id in pattern_assignment.event_ids:
                # Get session_id for this event
                ids_tuple = event_id_to_session_id_mapping.get(event_id)
                if not ids_tuple:
                    # Skip events without mapping - they'll fail enrichment anyway
                    continue
                _, session_id = ids_tuple
                # Only add if this session hasn't contributed to this pattern yet
                if session_id in pattern_session_seen[pattern_id]:
                    logger.warning(
                        f"Event {event_id} from session {session_id} already contributed to pattern {pattern_id}, skipping",
                        session_id=session_id,
                        signals_type="session-summaries",
                    )
                    continue
                pattern_session_seen[pattern_id].add(session_id)
                combined_patterns_assignments[pattern_id].append(event_id)
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
        abandonment=event[SessionSummaryIssueTypes.ABANDONMENT.value],
        confusion=event[SessionSummaryIssueTypes.CONFUSION.value],
        exception=event[SessionSummaryIssueTypes.EXCEPTION.value],
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
        msg = f"Segment name, outcome or success not found for segment index {target_segment_index} in session summary: {session_summary.data}"
        logger.error(msg, signals_type="session-summaries")
        raise ValueError(msg)
    return segment_name, segment_outcome, segment_success


def _enrich_pattern_assigned_event_with_session_summary_data(
    pattern_assigned_event: PatternAssignedEvent,
    db_summary: SingleSessionSummary,
    session_summary: SessionSummarySerializer,
    person: Person | None,
) -> PatternAssignedEventSegmentContext:
    """Attach session summary context to a pattern-assigned event."""
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
                    session_start_time_str=(
                        db_summary.session_start_time.isoformat() if db_summary.session_start_time else None
                    ),
                    session_duration=db_summary.session_duration,
                    person_distinct_ids=person.distinct_ids if person else [],
                    person_email=person.properties.get("email") if person else None,
                )
                return event_segment_context
            except Exception as err:
                msg = f"Error enriching pattern assigned event ({event}) with session summary data ({pattern_assigned_event}): {err}"
                logger.exception(msg, session_id=pattern_assigned_event.session_id, signals_type="session-summaries")
                raise SummaryValidationError(msg) from err
    msg = f"Session summary with the required event ({pattern_assigned_event}) was not found"
    logger.error(msg, session_id=pattern_assigned_event.session_id, signals_type="session-summaries")
    raise ValueError(msg)


def combine_patterns_ids_with_events_context(
    combined_event_ids_mappings: dict[str, tuple[str, str]],
    combined_patterns_assignments: dict[int, list[str]],
    session_id_to_ready_summaries_mapping: dict[str, SingleSessionSummary],
    session_id_to_person_mapping: dict[str, Person | None],
) -> dict[int, list[PatternAssignedEventSegmentContext]]:
    """Map pattern IDs to enriched event contexts using assignments context."""
    pattern_event_ids_mapping: dict[int, list[PatternAssignedEventSegmentContext]] = {}
    # Creating mapping to avoid serializing the sessions on every event
    session_id_to_serialized_summary_mapping = {
        session_id: session_summary_to_serializer(db_summary.summary)
        for session_id, db_summary in session_id_to_ready_summaries_mapping.items()
    }
    # Iterate over patterns to which we assigned event ids
    for pattern_id, event_ids in combined_patterns_assignments.items():
        for event_id in event_ids:
            # Find full session id and event uuid for the event id
            ids_tuple = combined_event_ids_mappings.get(event_id)
            if not ids_tuple:
                logger.exception(
                    f"Event uuid and session id not found for event_id {event_id} when combining patterns with event ids "
                    f"for pattern_id {pattern_id}",
                    signals_type="session-summaries",
                )
                # Skip the event
                continue
            event_uuid, session_id = ids_tuple
            pattern_assigned_event = PatternAssignedEvent(
                event_id=event_id, event_uuid=event_uuid, session_id=session_id
            )
            db_summary = session_id_to_ready_summaries_mapping.get(session_id)
            session_summary = session_id_to_serialized_summary_mapping.get(session_id)
            if not db_summary or not session_summary:
                logger.exception(
                    f"Session summary not found in the DB for session id {session_id} when combining patterns with event ids "
                    f"for pattern_id {pattern_id}",
                    session_id=session_id,
                    signals_type="session-summaries",
                )
                # Skip the event
                continue
            event_segment_context = _enrich_pattern_assigned_event_with_session_summary_data(
                pattern_assigned_event=pattern_assigned_event,
                db_summary=db_summary,
                session_summary=session_summary,
                person=session_id_to_person_mapping.get(session_id),
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
    session_ids: list[str],
    user_id: int,
) -> EnrichedSessionGroupSummaryPatternsList:
    """Attach event context and stats to each extracted pattern."""
    combined_patterns = []
    for pattern in patterns.patterns:
        pattern_id = pattern.pattern_id
        pattern_events = pattern_id_to_event_context_mapping.get(int(pattern_id))
        if not pattern_events:
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
    successful_patterns_count = len(combined_patterns)
    failed_patterns_count = len(patterns.patterns) - successful_patterns_count
    if minimum_expected_patterns_count > successful_patterns_count:
        exception_message = (
            f"Too many patterns failed to enrich with session meta, when summarizing {len(session_ids)} "
            f"sessions ({logging_session_ids(session_ids)}) for user {user_id}. "
            f"Input: {len(patterns.patterns)}; success: {successful_patterns_count} "
            f"(enriched: {len(combined_patterns)}); failure: {failed_patterns_count}"
        )
        logger.exception(exception_message, user_id=user_id, signals_type="session-summaries")
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
        msg = f"Error validating session summary against the schema ({err}): {session_summary_dict}"
        logger.exception(msg, signals_type="session-summaries")
        raise SummaryValidationError(msg) from err


def get_persons_for_sessions_from_distinct_ids(
    session_id_to_ready_summaries_mapping: dict[str, SingleSessionSummary], team_id: int
) -> dict[str, Person | None]:
    """Get persons for a list of session ids, and return a mapping of session id to person"""
    distinct_id_to_session_id_mapping: dict[str, list[str]] = {}
    for session_id, summary in session_id_to_ready_summaries_mapping.items():
        if not summary.distinct_id:
            continue
        if summary.distinct_id not in distinct_id_to_session_id_mapping:
            distinct_id_to_session_id_mapping[summary.distinct_id] = []
        distinct_id_to_session_id_mapping[summary.distinct_id].append(session_id)
    distinct_ids = list(distinct_id_to_session_id_mapping.keys())
    if not distinct_ids:
        # No ids to search for persons - return empty mapping
        return {}
    try:
        persons = get_persons_by_distinct_ids(team_id=team_id, distinct_ids=distinct_ids)
        persons = persons.prefetch_related(
            Prefetch(
                "persondistinctid_set",
                queryset=PersonDistinctId.objects.filter(team_id=team_id).order_by("id"),
                to_attr="distinct_ids_cache",
            )
        )
        session_id_to_person_mapping: dict[str, Person | None] = {}
        for person in persons.iterator(chunk_size=1000):
            for distinct_id in person.distinct_ids:
                person_session_ids = distinct_id_to_session_id_mapping.get(distinct_id)
                if not person_session_ids:
                    continue
                for person_session_id in person_session_ids:
                    session_id_to_person_mapping[person_session_id] = person
        return session_id_to_person_mapping
    except Exception as err:
        # As access to persons DB could fail, return empty mapping to avoid failing the activity
        logger.exception(
            f"Error getting persons for sessions from distinct ids ({distinct_ids}) for team {team_id} when summarizing sessions: {err}",
            team_id=team_id,
            signals_type="session-summaries",
        )
        return {}
