from enum import Enum
from typing import Any

import structlog
from rest_framework import serializers

from ee.hogai.session_summaries import SummaryValidationError
from ee.hogai.session_summaries.constants import HALLUCINATED_EVENTS_MIN_RATIO
from ee.hogai.session_summaries.utils import (
    calculate_time_since_start,
    get_column_index,
    prepare_datetime,
    unpack_full_event_id,
)
from ee.hogai.utils.yaml import load_yaml_from_raw_llm_content

logger = structlog.get_logger(__name__)


class SessionSummaryIssueTypes(str, Enum):
    ABANDONMENT = "abandonment"
    CONFUSION = "confusion"
    EXCEPTION = "exception"


class SessionSummaryExceptionTypes(str, Enum):
    BLOCKING = "blocking"
    NON_BLOCKING = "non-blocking"


class RawKeyActionSerializer(serializers.Serializer):
    description = serializers.CharField(min_length=1, max_length=1024, required=False, allow_null=True)
    abandonment = serializers.BooleanField(required=False, default=False, allow_null=True)
    confusion = serializers.BooleanField(required=False, default=False, allow_null=True)
    exception = serializers.ChoiceField(
        choices=[e.value for e in SessionSummaryExceptionTypes], required=False, allow_null=True
    )
    event_id = serializers.CharField(min_length=1, max_length=128, required=False, allow_null=True)


class IntermediateKeyActionSerializer(RawKeyActionSerializer):
    """
    Key actions enriched with metadata, but limited set to not feed LLM excessive info
    when the single summary is not a final step (for example, group summaries)
    """

    timestamp = serializers.CharField(max_length=128, required=False, allow_null=True)
    milliseconds_since_start = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    window_id = serializers.CharField(max_length=128, required=False, allow_null=True)
    current_url = serializers.CharField(min_length=1, required=False, allow_null=True)
    event = serializers.CharField(min_length=1, max_length=128, required=False, allow_null=True)
    event_type = serializers.CharField(max_length=128, required=False, allow_null=True)
    event_index = serializers.IntegerField(min_value=0, required=False, allow_null=True)


class EnrichedKeyActionSerializer(IntermediateKeyActionSerializer):
    """
    LLM actions enriched with metadata, expected to be used in the final summary.
    """

    session_id = serializers.CharField(max_length=128, required=False, allow_null=True)
    event_uuid = serializers.CharField(max_length=128, required=False, allow_null=True)


class RawSegmentKeyActionsSerializer(serializers.Serializer):
    """
    Key actions grouped by segment.
    """

    segment_index = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    events = serializers.ListField(child=RawKeyActionSerializer(), required=False, allow_empty=True, allow_null=True)


class IntermediateSegmentKeyActionsSerializer(RawSegmentKeyActionsSerializer):
    """
    Key actions grouped by segment, enriched with metadata, but limited set to not feed LLM excessive info
    when the single summary is not a final step (for example, group summaries)
    """

    events = serializers.ListField(
        child=IntermediateKeyActionSerializer(), required=False, allow_empty=True, allow_null=True
    )


class EnrichedSegmentKeyActionsSerializer(IntermediateSegmentKeyActionsSerializer):
    """
    Key actions grouped by segment, enriched with metadata, expected to be used in the final summary.
    """

    events = serializers.ListField(
        child=EnrichedKeyActionSerializer(), required=False, allow_empty=True, allow_null=True
    )


class RawSegmentSerializer(serializers.Serializer):
    """
    Segments coming from LLM.
    """

    index = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    name = serializers.CharField(min_length=1, max_length=256, required=False, allow_null=True)
    start_event_id = serializers.CharField(min_length=1, max_length=128, required=False, allow_null=True)
    end_event_id = serializers.CharField(min_length=1, max_length=128, required=False, allow_null=True)


class SegmentMetaSerializer(serializers.Serializer):
    """
    Calculated metadata for each segment.
    """

    duration = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    duration_percentage = serializers.FloatField(min_value=0, max_value=1, required=False, allow_null=True)
    events_count = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    events_percentage = serializers.FloatField(min_value=0, max_value=1, required=False, allow_null=True)
    key_action_count = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    failure_count = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    abandonment_count = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    confusion_count = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    exception_count = serializers.IntegerField(min_value=0, required=False, allow_null=True)


class EnrichedSegmentSerializer(RawSegmentSerializer):
    """
    Segments enriched with metadata.
    """

    meta = SegmentMetaSerializer(required=False, allow_null=True)


class OutcomeSerializer(serializers.Serializer):
    """
    Initial goal and session outcome coming from LLM.
    """

    description = serializers.CharField(min_length=1, max_length=1024, required=False, allow_null=True)
    success = serializers.BooleanField(required=False, allow_null=True)


class SegmentOutcomeSerializer(serializers.Serializer):
    """
    Outcome for each segment.
    """

    segment_index = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    summary = serializers.CharField(min_length=1, max_length=1024, required=False, allow_null=True)
    success = serializers.BooleanField(required=False, allow_null=True)


class RawSessionSummarySerializer(serializers.Serializer):
    """
    Raw session summary coming from LLM.
    """

    segments = serializers.ListField(child=RawSegmentSerializer(), required=False, allow_empty=True, allow_null=True)
    key_actions = serializers.ListField(
        child=RawSegmentKeyActionsSerializer(), required=False, allow_empty=True, allow_null=True
    )
    segment_outcomes = serializers.ListField(
        child=SegmentOutcomeSerializer(), required=False, allow_empty=True, allow_null=True
    )
    session_outcome = OutcomeSerializer(required=False, allow_null=True)


class IntermediateSessionSummarySerializer(RawSessionSummarySerializer):
    """
    Session summary enriched with metadata, but limited set to not feed LLM excessive info
    when the single summary is not a final step (for example, group summaries)
    """

    segments = serializers.ListField(
        child=EnrichedSegmentSerializer(), required=False, allow_empty=True, allow_null=True
    )
    key_actions = serializers.ListField(
        child=IntermediateSegmentKeyActionsSerializer(), required=False, allow_empty=True, allow_null=True
    )


class SessionSummarySerializer(IntermediateSessionSummarySerializer):
    """
    Session summary enriched with metadata, expected to be used in the final summary.
    """

    key_actions = serializers.ListField(
        child=EnrichedSegmentKeyActionsSerializer(), required=False, allow_empty=True, allow_null=True
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """
        Validate that all LLM-generated fields are present and properly filled.
        Fields are optional during streaming but must be complete in final output.
        """
        if self.context.get("streaming_validation"):
            # Disable strict validation for streaming, as the context could be incomplete
            return attrs
        errors: dict[str, list[str]] = {}
        # Validate top-level fields
        segments = attrs.get("segments")
        if segments is None or len(segments) == 0:
            errors["segments"] = ["This field is required and must not be empty."]
        key_actions = attrs.get("key_actions")
        if key_actions is None or len(key_actions) == 0:
            errors["key_actions"] = ["This field is required and must not be empty."]
        segment_outcomes = attrs.get("segment_outcomes")
        if segment_outcomes is None or len(segment_outcomes) == 0:
            errors["segment_outcomes"] = ["This field is required and must not be empty."]
        session_outcome = attrs.get("session_outcome")
        if session_outcome is None:
            errors["session_outcome"] = ["This field is required."]
        # Validate each segment
        if segments:
            for i, segment in enumerate(segments):
                if segment.get("index") is None:
                    errors[f"segments[{i}].index"] = ["This field is required."]
                if segment.get("name") is None:
                    errors[f"segments[{i}].name"] = ["This field is required."]
                if segment.get("start_event_id") is None:
                    errors[f"segments[{i}].start_event_id"] = ["This field is required."]
                if segment.get("end_event_id") is None:
                    errors[f"segments[{i}].end_event_id"] = ["This field is required."]
        # Validate each key_actions group
        if key_actions:
            for i, key_action_group in enumerate(key_actions):
                if key_action_group.get("segment_index") is None:
                    errors[f"key_actions[{i}].segment_index"] = ["This field is required."]
                events = key_action_group.get("events")
                if events is None or len(events) == 0:
                    errors[f"key_actions[{i}].events"] = ["This field is required and must not be empty."]
                else:
                    # Validate each event
                    for j, event in enumerate(events):
                        if event.get("event_id") is None:
                            errors[f"key_actions[{i}].events[{j}].event_id"] = ["This field is required."]
                        if event.get("description") is None:
                            errors[f"key_actions[{i}].events[{j}].description"] = ["This field is required."]
                        if not isinstance(event.get("abandonment"), bool):
                            errors[f"key_actions[{i}].events[{j}].abandonment"] = ["This field must be a boolean."]
                        if not isinstance(event.get("confusion"), bool):
                            errors[f"key_actions[{i}].events[{j}].confusion"] = ["This field must be a boolean."]
                        if "exception" not in event:
                            errors[f"key_actions[{i}].events[{j}].exception"] = ["This field is required."]
        # Validate each segment_outcome
        if segment_outcomes:
            for i, outcome in enumerate(segment_outcomes):
                if outcome.get("segment_index") is None:
                    errors[f"segment_outcomes[{i}].segment_index"] = ["This field is required."]
                if outcome.get("summary") is None:
                    errors[f"segment_outcomes[{i}].summary"] = ["This field is required."]
                if not isinstance(outcome.get("success"), bool):
                    errors[f"segment_outcomes[{i}].success"] = ["This field must be a boolean."]
        # Validate session_outcome
        if session_outcome:
            if session_outcome.get("description") is None:
                errors["session_outcome.description"] = ["This field is required."]
            if not isinstance(session_outcome.get("success"), bool):
                errors["session_outcome.success"] = ["This field must be a boolean."]
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


def _remove_hallucinated_events(
    hallucinated_events: list[tuple[int, int, dict[str, Any]]],
    raw_session_summary: RawSessionSummarySerializer,
    total_summary_events: int,
    session_id: str,
    final_validation: bool,
) -> RawSessionSummarySerializer:
    """
    Remove hallucinated events from the key actions in the raw session summary.
    """
    # If too many events are hallucinated for the final check - fail the summarization
    if (
        final_validation
        and total_summary_events > 0
        and len(hallucinated_events) / total_summary_events > HALLUCINATED_EVENTS_MIN_RATIO
    ):
        msg = (
            f"Too many hallucinated events ({len(hallucinated_events)}/{total_summary_events}) for session id ({session_id})"
            f"in the raw session summary: {[x[-1] for x in hallucinated_events]} "
        )
        if final_validation:
            logger.error(msg, session_id=session_id, signals_type="session-summaries")
        raise SummaryValidationError(msg)
    # Reverse to not break indexes
    for group_index, event_index, event in reversed(hallucinated_events):
        if final_validation:
            # Log only on final validation to not spam during regular streaming (as validation errors are expected)
            logger.warning(
                f"Removing hallucinated event {event} from the raw session summary for session_id {session_id}",
                session_id=session_id,
                signals_type="session-summaries",
            )
        del raw_session_summary.data["key_actions"][group_index]["events"][event_index]
    return raw_session_summary


def load_raw_session_summary_from_llm_content(
    raw_content: str, allowed_event_ids: list[str], session_id: str, *, final_validation: bool
) -> RawSessionSummarySerializer | None:
    if not raw_content:
        msg = f"No LLM content found when summarizing session_id {session_id}"
        if final_validation:
            # Log only on final validation to not spam during regular streaming (as validation errors are expected)
            logger.error(msg, session_id=session_id, signals_type="session-summaries")
        raise SummaryValidationError(msg)
    try:
        json_content = load_yaml_from_raw_llm_content(raw_content=raw_content, final_validation=final_validation)
        if not isinstance(json_content, dict):
            raise Exception(f"LLM output is not a dictionary: {raw_content}")
    except Exception as err:
        msg = f"Error loading YAML content into JSON when summarizing session_id {session_id}: {err}"
        if final_validation:
            logger.exception(msg, session_id=session_id, signals_type="session-summaries")
        raise SummaryValidationError(msg) from err
    # Validate the LLM output against the schema
    raw_session_summary = RawSessionSummarySerializer(data=json_content)
    if not raw_session_summary.is_valid():
        msg = f"Error validating LLM output against the schema when summarizing session_id {session_id}: {raw_session_summary.errors}"
        if final_validation:
            logger.error(msg, session_id=session_id, signals_type="session-summaries")
        raise SummaryValidationError(msg)
    segments = raw_session_summary.data.get("segments")
    if not segments:
        # If segments aren't generated yet - return the current state
        return raw_session_summary
    segments_indices = [segment.get("index") for segment in segments]
    key_actions = raw_session_summary.data.get("key_actions")
    total_summary_events = 0
    hallucinated_events: list[tuple[int, int, dict[str, Any]]] = []
    if not key_actions:
        # If key actions aren't generated yet - return the current state
        return raw_session_summary
    for group_index, key_action_group in enumerate(key_actions):
        key_group_segment_index = key_action_group.get("segment_index")
        if key_group_segment_index is None:
            # If key group segment index isn't generated yet - skip this group
            continue
        # Ensure that LLM didn't hallucinate segments
        if key_group_segment_index not in segments_indices:
            msg = f"LLM hallucinated segment index {key_group_segment_index} when summarizing session_id {session_id}: {raw_session_summary.data}"
            logger.error(msg, session_id=session_id, signals_type="session-summaries")
            # No sense to continue generation if the whole segment is hallucinated
            raise ValueError(msg)
        key_group_events = key_action_group.get("events")
        if not key_group_events:
            # If key group events aren't generated yet - skip this group
            continue
        for event_index, event in enumerate(key_group_events):
            total_summary_events += 1
            # Ensure that LLM didn't hallucinate events
            event_id = event.get("event_id")
            if not event_id or len(event_id) != 8:
                # If event ID isn't fully generated yet - skip this event
                continue
            # Skip hallucinated events
            if event_id not in allowed_event_ids:
                hallucinated_events.append((group_index, event_index, event))
                continue
    # TODO: Investigate how to reduce their appearance in the first place
    raw_session_summary = _remove_hallucinated_events(
        hallucinated_events=hallucinated_events,
        raw_session_summary=raw_session_summary,
        total_summary_events=total_summary_events,
        session_id=session_id,
        final_validation=final_validation,
    )
    return raw_session_summary


def _validate_enriched_summary(
    data: dict[str, Any], session_id: str, final_validation: bool
) -> SessionSummarySerializer:
    # Avoid strict validation, if it's not the final step, as the context could be incomplete because of the streaming
    session_summary = SessionSummarySerializer(data=data, context={"streaming_validation": not final_validation})
    # Validate even when processing incomplete chunks as the `.data` can't be used without validation check
    if not session_summary.is_valid():
        # Most of the fields are optional, so failed validation should be reported
        msg = f"Error validating enriched content against the schema when summarizing session_id {session_id}: {session_summary.errors}"
        logger.error(msg, session_id=session_id, signals_type="session-summaries")
        raise SummaryValidationError(msg)
    return session_summary


def _pick_start_end_events(
    start_event_id: str,
    end_event_id: str,
    event_index_index: int,
    simplified_events_mapping: dict[str, list[Any]],
) -> tuple[list[Any], list[Any]]:
    start_event = simplified_events_mapping[start_event_id]
    end_event = simplified_events_mapping[end_event_id]
    # If events are in the correct order - return them as is
    if start_event[event_index_index] < end_event[event_index_index]:
        return start_event, end_event
    # If events are in the wrong order - swap them
    return end_event, start_event


def _calculate_segment_duration(
    start_event_id: str,
    end_event_id: str,
    timestamp_index: int,
    event_index_index: int,
    simplified_events_mapping: dict[str, list[Any]],
    session_total_duration: int,
) -> tuple[int, float]:
    start_event, end_event = _pick_start_end_events(
        start_event_id=start_event_id,
        end_event_id=end_event_id,
        event_index_index=event_index_index,
        simplified_events_mapping=simplified_events_mapping,
    )
    start_event_timestamp = prepare_datetime(start_event[timestamp_index])
    end_event_timestamp = prepare_datetime(end_event[timestamp_index])
    duration = int((end_event_timestamp - start_event_timestamp).total_seconds())
    # Round to avoid floating point precision issues (like 1.0000000002)
    duration_percentage = round(duration / session_total_duration, 4)
    if duration_percentage > 1 and duration_percentage < 1.1:  # Round up to 100%
        return duration, 1.0
    # If miscalculation is too large (probably, a hallucination) - keep it 0 and hope for the fallback recalculation
    if duration_percentage > 1 or duration_percentage < 0:
        return 0, 0.0
    return duration, duration_percentage


def _calculate_segment_events_count(
    start_event_id: str,
    end_event_id: str,
    event_index_index: int,
    simplified_events_mapping: dict[str, list[Any]],
) -> tuple[int, float]:
    start_event, end_event = _pick_start_end_events(
        start_event_id=start_event_id,
        end_event_id=end_event_id,
        event_index_index=event_index_index,
        simplified_events_mapping=simplified_events_mapping,
    )
    events_count = end_event[event_index_index] - start_event[event_index_index] + 1
    # Round to avoid floating point precision issues (like 1.0000000002)
    events_percentage = round(events_count / len(simplified_events_mapping), 4)
    if events_percentage > 1 and events_percentage < 1.1:  # Round up to 100%
        events_percentage = 1.0
    return events_count, events_percentage


def _calculate_segment_meta(
    raw_segment: dict[str, Any],
    timestamp_index: int,
    event_index_index: int,
    simplified_events_mapping: dict[str, list[Any]],
    raw_key_actions: list[dict[str, Any]] | None,
    session_duration: int,
    session_id: str,
    final_validation: bool,
) -> SegmentMetaSerializer:
    # Find first and the last event in the segment
    segment_index = raw_segment.get("index")
    start_event_id = raw_segment.get("start_event_id")
    end_event_id = raw_segment.get("end_event_id")
    segment_meta_data: dict[str, Any] = {}
    if (
        segment_index is None
        or start_event_id is None
        or end_event_id is None
        # All the proper event IDs are 8 characters long
        # If shorter - could still not fully streamed yet
        or len(start_event_id) != 8
        or len(end_event_id) != 8
    ):
        # If segment index, start, or end event ID aren't generated yet - return empty meta
        return SegmentMetaSerializer(data=segment_meta_data)
    # Calculate duration of the segment
    if not session_duration:
        msg = f"Session duration is not set when summarizing session_id {session_id}"
        logger.error(msg, session_id=session_id, signals_type="session-summaries")
        raise ValueError(msg)
    # If both events aren't hallucinated - calculate the meta
    if start_event_id in simplified_events_mapping and end_event_id in simplified_events_mapping:
        duration, duration_percentage = _calculate_segment_duration(
            start_event_id=start_event_id,
            end_event_id=end_event_id,
            timestamp_index=timestamp_index,
            event_index_index=event_index_index,
            simplified_events_mapping=simplified_events_mapping,
            session_total_duration=session_duration,
        )
    # If hallucinated - avoid calculating it now and hope for the fallback from the key actions
    else:
        duration, duration_percentage = 0, 0.0
    # If the end event is before the start event (or start/end event ids are hallucinated) - avoid enriching the segment, for now
    # The goal is to fill it later from the key actions (better have part of the data than none)
    if duration <= 0:
        segment_meta_data["duration"] = 0
        segment_meta_data["duration_percentage"] = 0.0
        segment_meta_data["events_count"] = 0
        segment_meta_data["events_percentage"] = 0.0
    else:
        segment_meta_data["duration"] = duration
        segment_meta_data["duration_percentage"] = duration_percentage
        # Calculate events count and percentage of the segment
        events_count, events_percentage = _calculate_segment_events_count(
            start_event_id=start_event_id,
            end_event_id=end_event_id,
            event_index_index=event_index_index,
            simplified_events_mapping=simplified_events_mapping,
        )
        # No additional index check here as events sorted chronologically
        segment_meta_data["events_count"] = events_count
        segment_meta_data["events_percentage"] = events_percentage
    # Search for key actions linked to the segment
    if not raw_key_actions:
        # If no key actions are generated yet
        return SegmentMetaSerializer(data=segment_meta_data)
    segment_key_actions_group = None
    # Find a relevant key actions group for the segment
    for key_actions_group in raw_key_actions:
        key_group_segment_index = key_actions_group.get("segment_index")
        if key_group_segment_index is None or key_group_segment_index != segment_index:
            # If key group segment index isn't generated yet or doesn't match the segment index - skip this group
            continue
        segment_key_actions_group = key_actions_group
        break
    # If no relevant key actions group is found
    if not segment_key_actions_group:
        return SegmentMetaSerializer(data=segment_meta_data)
    # Process the relevant events from the key actions group
    key_group_events = segment_key_actions_group.get("events", [])
    if not key_group_events:
        # If key events aren't generated yet
        return SegmentMetaSerializer(data=segment_meta_data)
    segment_meta_data["key_action_count"] = len(key_group_events)
    # Calculate failure count
    failure_count = 0
    abandonment_count = 0
    confusion_count = 0
    exception_count = 0
    for key_action_event in key_group_events:
        abandonment = key_action_event.get(SessionSummaryIssueTypes.ABANDONMENT.value)
        confusion = key_action_event.get(SessionSummaryIssueTypes.CONFUSION.value)
        exception = key_action_event.get(SessionSummaryIssueTypes.EXCEPTION.value)
        # Count each type of issue
        if abandonment:
            abandonment_count += 1
        if confusion:
            confusion_count += 1
        if exception:
            exception_count += 1
        # If any of the fields indicate a failure, increment the total count
        if abandonment or confusion or exception:
            failure_count += 1
    segment_meta_data["failure_count"] = failure_count
    segment_meta_data["abandonment_count"] = abandonment_count
    segment_meta_data["confusion_count"] = confusion_count
    segment_meta_data["exception_count"] = exception_count
    # Fallback - if enough events processed and the data drastically changes - calculate the meta from the key actions
    if len(key_group_events) < 2:
        # If not enough events yet
        return SegmentMetaSerializer(data=segment_meta_data)
    # Calculate key action count and failure count
    fallback_start_event_id = key_group_events[0].get("event_id")
    fallback_end_event_id = key_group_events[-1].get("event_id")
    if (
        fallback_start_event_id is None
        or fallback_end_event_id is None
        # All the proper event IDs are 8 characters long
        # If shorter - could still not fully streamed yet
        or len(fallback_start_event_id) != 8
        or len(fallback_end_event_id) != 8
    ):
        # If event ids aren't generated yet
        return SegmentMetaSerializer(data=segment_meta_data)
    if (
        fallback_start_event_id not in simplified_events_mapping
        or fallback_end_event_id not in simplified_events_mapping
    ):
        # If event ids are hallucinated and fallback can't be calculated also
        return SegmentMetaSerializer(data=segment_meta_data)
    fallback_duration, fallback_duration_percentage = _calculate_segment_duration(
        start_event_id=fallback_start_event_id,
        end_event_id=fallback_end_event_id,
        timestamp_index=timestamp_index,
        event_index_index=event_index_index,
        simplified_events_mapping=simplified_events_mapping,
        session_total_duration=session_duration,
    )
    fallback_events_count, fallback_events_percentage = _calculate_segment_events_count(
        start_event_id=fallback_start_event_id,
        end_event_id=fallback_end_event_id,
        event_index_index=event_index_index,
        simplified_events_mapping=simplified_events_mapping,
    )
    if fallback_duration == 0:
        # If fallback_duration is also 0, calculations are not reliable
        return SegmentMetaSerializer(data=segment_meta_data)
    # If the change is drastic, or no duration at all - use the fallback data to avoid reader's confusion
    # Avoiding downsizing the segment as larger segments make more sense visually
    # TODO: Factor of two is arbitrary, find a better solution
    if duration <= 0 or fallback_duration // duration > 2:
        # Checking only duration as events are sorted chronologically
        if final_validation:
            logger.warning(
                f"Duration change is drastic (fallback: {fallback_duration} -> segments: {duration}) - using fallback data for session_id {session_id}",
                session_id=session_id,
                signals_type="session-summaries",
            )
        segment_meta_data["duration"] = fallback_duration
        segment_meta_data["duration_percentage"] = fallback_duration_percentage
        segment_meta_data["events_count"] = fallback_events_count
        segment_meta_data["events_percentage"] = fallback_events_percentage
        return SegmentMetaSerializer(data=segment_meta_data)

    # TODO Calculate unique URLs in the segment as a stat?
    # TODO Calculate unique window IDs in the segment as a stat?

    return SegmentMetaSerializer(data=segment_meta_data)


def enrich_raw_session_summary_with_meta(
    raw_session_summary: RawSessionSummarySerializer,
    simplified_events_mapping: dict[str, list[Any]],
    event_ids_mapping: dict[str, str],
    simplified_events_columns: list[str],
    url_mapping_reversed: dict[str, str],
    window_mapping_reversed: dict[str, str],
    session_id: str,
    session_start_time_str: str,
    session_duration: int,
    final_validation: bool,
) -> SessionSummarySerializer:
    timestamp_index = get_column_index(simplified_events_columns, "timestamp")
    window_id_index = get_column_index(simplified_events_columns, "$window_id")
    current_url_index = get_column_index(simplified_events_columns, "$current_url")
    event_index = get_column_index(simplified_events_columns, "event")
    event_type_index = get_column_index(simplified_events_columns, "$event_type")
    event_index_index = get_column_index(simplified_events_columns, "event_index")
    raw_segments = raw_session_summary.data.get("segments")
    raw_key_actions = raw_session_summary.data.get("key_actions")
    summary_to_enrich = dict(raw_session_summary.data)
    session_start_time = prepare_datetime(session_start_time_str)
    # Enrich LLM segments with metadata
    enriched_segments = []
    if not raw_segments:
        # If segments aren't generated yet - return the current state
        session_summary = _validate_enriched_summary(
            data=raw_session_summary.data, session_id=session_id, final_validation=final_validation
        )
        return session_summary
    for raw_segment in raw_segments:
        enriched_segment = dict(raw_segment)
        # Calculate segment meta
        segment_meta = _calculate_segment_meta(
            raw_segment=raw_segment,
            session_duration=session_duration,
            timestamp_index=timestamp_index,
            event_index_index=event_index_index,
            simplified_events_mapping=simplified_events_mapping,
            raw_key_actions=raw_key_actions,
            session_id=session_id,
            final_validation=final_validation,
        )
        # Validate the serializer to be able to use `.data`
        if not segment_meta.is_valid():
            # Most of the fields are optional, so failed validation should be reported
            msg = f"Error validating segment meta against the schema when summarizing session_id {session_id}: {segment_meta.errors}"
            if final_validation:
                logger.error(msg, session_id=session_id, signals_type="session-summaries")
            raise SummaryValidationError(msg)
        enriched_segment["meta"] = segment_meta.data
        enriched_segments.append(enriched_segment)
    summary_to_enrich["segments"] = enriched_segments
    # Enrich LLM events with metadata
    enriched_key_actions = []
    if not raw_key_actions:
        # If key actions aren't generated yet - return the current state
        session_summary = _validate_enriched_summary(
            data=summary_to_enrich, session_id=session_id, final_validation=final_validation
        )
        return session_summary
    # Iterate over key actions groups per segment
    for key_action_group in raw_key_actions:
        enriched_events = []
        segment_index = key_action_group.get("segment_index")
        if segment_index is None:
            # If segment index isn't generated yet - skip this group
            continue
        events = key_action_group.get("events", [])
        if not events:
            # If events aren't generated yet - skip this group
            continue
        for event in events:
            enriched_event = dict(event)
            event_id: str | None = event.get("event_id")
            if not event_id or len(event_id) != 8:
                # If event ID isn't fully generated yet - skip this event
                continue
            event_mapping_data = simplified_events_mapping.get(event_id)
            if not event_mapping_data:
                # If event id is found, but not in mapping, it's a hallucination
                msg = f"Mapping data for event_id {event_id} not found when summarizing session_id {session_id} (probably a hallucination): {raw_session_summary}"
                logger.error(msg, session_id=session_id, signals_type="session-summaries")
                raise ValueError(msg)
            enriched_event["event"] = event_mapping_data[event_index]
            # Calculate time to jump to the right place in the player
            timestamp = event_mapping_data[timestamp_index]
            enriched_event["timestamp"] = timestamp
            ms_since_start = calculate_time_since_start(timestamp, session_start_time)
            if ms_since_start is not None:
                enriched_event["milliseconds_since_start"] = ms_since_start
            # Add full URL of the event page
            current_url = event_mapping_data[current_url_index]
            # Some events (like Python SDK ones) could have no URL (as it's added by the web library)
            enriched_event["current_url"] = url_mapping_reversed.get(current_url)
            # Add window ID of the event
            window_id = event_mapping_data[window_id_index]
            # Some events (like Python SDK ones) could have no window ID (as it's added by the web library)
            enriched_event["window_id"] = window_mapping_reversed.get(window_id)
            # Add event type (if applicable)
            event_type = event_mapping_data[event_type_index]
            if event_type:
                enriched_event["event_type"] = event_type
            # Add event index to better link summary event with an actual event
            enriched_event["event_index"] = event_mapping_data[event_index_index]
            # Add session/event UUIDs to better track events across sessions
            enriched_event["session_id"], enriched_event["event_uuid"] = unpack_full_event_id(
                full_event_id=event_ids_mapping.get(event_id), session_id=session_id
            )
            enriched_events.append(enriched_event)
        # Ensure chronological order of the events
        enriched_events.sort(key=lambda x: x.get("milliseconds_since_start", 0))
        enriched_key_actions.append({"segment_index": segment_index, "events": enriched_events})
    # Validate the enriched content against the schema
    summary_to_enrich["key_actions"] = enriched_key_actions
    session_summary = _validate_enriched_summary(
        data=summary_to_enrich, session_id=session_id, final_validation=final_validation
    )
    return session_summary
