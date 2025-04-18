from datetime import datetime
from typing import Any
from jsonschema import ValidationError
from rest_framework import serializers
import yaml

from ee.session_recordings.session_summary.utils import get_column_index


class RawKeyActionSerializer(serializers.Serializer):
    description = serializers.CharField(min_length=1, max_length=1024, required=False, allow_null=True)
    error = serializers.BooleanField(required=False, default=None, allow_null=True)
    event_id = serializers.CharField(min_length=1, max_length=128, required=False, allow_null=True)


class EnrichedKeyActionSerializer(RawKeyActionSerializer):
    """
    LLM actions enriched with metadata.
    """

    timestamp = serializers.CharField(max_length=128, required=False, allow_null=True)
    milliseconds_since_start = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    window_id = serializers.CharField(max_length=128, required=False, allow_null=True)
    current_url = serializers.CharField(min_length=1, required=False, allow_null=True)
    event = serializers.CharField(min_length=1, max_length=128, required=False, allow_null=True)
    event_type = serializers.CharField(max_length=128, required=False, allow_null=True)
    event_index = serializers.IntegerField(min_value=0, required=False, allow_null=True)


class RawObjectiveKeyActionsSerializer(serializers.Serializer):
    """
    Key actions grouped by objective.
    """

    objective = serializers.CharField(min_length=1, max_length=256, required=False, allow_null=True)
    events = serializers.ListField(child=RawKeyActionSerializer(), required=False, allow_empty=True, allow_null=True)


class EnrichedObjectiveKeyActionsSerializer(serializers.Serializer):
    """
    Key actions grouped by objective, enriched with metadata.
    """

    objective = serializers.CharField(min_length=1, max_length=256, required=False, allow_null=True)
    events = serializers.ListField(
        child=EnrichedKeyActionSerializer(), required=False, allow_empty=True, allow_null=True
    )


class ObjectiveSerializer(serializers.Serializer):
    """
    Objectives coming from LLM.
    """

    name = serializers.CharField(min_length=1, max_length=256, required=False, allow_null=True)
    summary = serializers.CharField(min_length=1, max_length=1024, required=False, allow_null=True)
    success = serializers.BooleanField(required=False, allow_null=True)


class OutcomeSerializer(serializers.Serializer):
    """
    Initial goal and session outcome coming from LLM.
    """

    description = serializers.CharField(min_length=1, max_length=1024, required=False, allow_null=True)
    success = serializers.BooleanField(required=False, allow_null=True)


class RawSessionSummarySerializer(serializers.Serializer):
    """
    Raw session summary coming from LLM.
    """

    objectives = serializers.ListField(child=ObjectiveSerializer(), required=False, allow_empty=True, allow_null=True)
    key_actions = serializers.ListField(
        child=RawObjectiveKeyActionsSerializer(), required=False, allow_empty=True, allow_null=True
    )
    session_outcome = OutcomeSerializer(required=False, allow_null=True)


class SessionSummarySerializer(serializers.Serializer):
    """
    Session summary enriched with metadata.
    """

    objectives = serializers.ListField(child=ObjectiveSerializer(), required=False, allow_empty=True, allow_null=True)
    key_actions = serializers.ListField(
        child=EnrichedObjectiveKeyActionsSerializer(), required=False, allow_empty=True, allow_null=True
    )
    session_outcome = OutcomeSerializer(required=False, allow_null=True)


def load_raw_session_summary_from_llm_content(
    raw_content: str, allowed_event_ids: list[str], session_id: str
) -> RawSessionSummarySerializer | None:
    try:
        # Strip the first and the last line of the content to load the YAML data only into JSON
        # TODO Work on a more robust solution
        json_content: dict = yaml.safe_load(raw_content.strip("```yaml\n").strip("```").strip())  # noqa: B005
    except Exception as e:
        raise ValidationError(f"Error loading YAML content into JSON when summarizing session_id {session_id}: {e}")
    # Validate the LLM output against the schema
    raw_session_summary = RawSessionSummarySerializer(data=json_content)
    if not raw_session_summary.is_valid():
        raise ValidationError(
            f"Error validating LLM output against the schema when summarizing session_id {session_id}: {raw_session_summary.errors}"
        )
    objectives = raw_session_summary.data.get("objectives")
    if not objectives:
        # If objectives aren't generated yet - return the current state
        return raw_session_summary
    objectives_names = [objective.get("name") for objective in objectives]
    key_actions = raw_session_summary.data.get("key_actions")
    if not key_actions:
        # If key actions aren't generated yet - return the current state
        return raw_session_summary
    for key_action_group in key_actions:
        key_group_objective = key_action_group.get("objective")
        if not key_group_objective:
            # If key group objective isn't generated yet - skip this group
            continue
        # Ensure that LLM didn't hallucinate objectives
        if key_group_objective not in objectives_names:
            raise ValueError(
                f"LLM hallucinated objective {key_group_objective} when summarizing session_id {session_id}: {raw_session_summary.data}"
            )
        key_group_events = key_action_group.get("events")
        if not key_group_events:
            # If key group events aren't generated yet - skip this group
            continue
        for event in key_group_events:
            # Ensure that LLM didn't hallucinate events
            event_id = event.get("event_id")
            if not event_id:
                # If event ID isn't generated yet - skip this event
                continue
            # TODO: Allow skipping some events (even if not too many to speed up the process
            if event_id not in allowed_event_ids:
                raise ValueError(
                    f"LLM hallucinated event_id {event_id} when summarizing session_id "
                    f"{session_id}: {raw_session_summary.data}"
                )
    return raw_session_summary


# TODO Rework the logic, so events before the recording are marked as "LOAD", not 00:00
def calculate_time_since_start(session_timestamp: str, session_start_time: datetime | None) -> int | None:
    if not session_start_time or not session_timestamp:
        return None
    timestamp_datetime = datetime.fromisoformat(session_timestamp)
    # TODO Check why the event could happen before the session started
    return max(0, int((timestamp_datetime - session_start_time).total_seconds() * 1000))


def _validate_enriched_summary(data: dict[str, Any], session_id: str) -> SessionSummarySerializer:
    session_summary = SessionSummarySerializer(data=data)
    # Validating even when processing incomplete chunks as the `.data` can't be used without validation check
    if not session_summary.is_valid():
        # Most of the fields are optional, so failed validation should be reported
        raise ValidationError(
            f"Error validating enriched content against the schema when summarizing session_id {session_id}: {session_summary.errors}"
        )
    return session_summary


def enrich_raw_session_summary_with_events_meta(
    raw_session_summary: RawSessionSummarySerializer,
    simplified_events_mapping: dict[str, list[Any]],
    simplified_events_columns: list[str],
    url_mapping_reversed: dict[str, str],
    window_mapping_reversed: dict[str, str],
    session_start_time: datetime,
    session_id: str,
) -> SessionSummarySerializer:
    timestamp_index = get_column_index(simplified_events_columns, "timestamp")
    window_id_index = get_column_index(simplified_events_columns, "$window_id")
    current_url_index = get_column_index(simplified_events_columns, "$current_url")
    event_index = get_column_index(simplified_events_columns, "event")
    event_type_index = get_column_index(simplified_events_columns, "$event_type")
    event_index_index = get_column_index(simplified_events_columns, "event_index")
    # Enrich LLM events with metadata
    enriched_key_actions = []
    key_actions = raw_session_summary.data.get("key_actions", [])
    if not key_actions:
        # If key actions aren't generated yet - return the current state
        session_summary = _validate_enriched_summary(raw_session_summary.data, session_id)
        return session_summary
    # Iterate over key actions groups per objective
    for key_action_group in key_actions:
        enriched_events = []
        objective = key_action_group.get("objective")
        if not objective:
            # If objective isn't generated yet - skip this group
            continue
        events = key_action_group.get("events", [])
        if not events:
            # If events aren't generated yet - skip this group
            continue
        for event in events:
            enriched_event = dict(event)
            event_id: str | None = event.get("event_id")
            if not event_id:
                # If event_id isn't generated yet - skip this event
                continue
            event_mapping_data = simplified_events_mapping.get(event_id)
            if not event_mapping_data:
                # If event id is found, but not in mapping, it's a hallucination
                raise ValueError(
                    f"Mapping data for event_id {event_id} not found when summarizing session_id {session_id} (probably a hallucination): {raw_session_summary}"
                )
            enriched_event["event"] = event_mapping_data[event_index]
            # Calculate time to jump to the right place in the player
            timestamp = event_mapping_data[timestamp_index]
            enriched_event["timestamp"] = timestamp
            ms_since_start = calculate_time_since_start(timestamp, session_start_time)
            if ms_since_start is not None:
                enriched_event["milliseconds_since_start"] = ms_since_start
            # Add full URL of the event page
            current_url = event_mapping_data[current_url_index]
            full_current_url = url_mapping_reversed.get(current_url)
            if not full_current_url:
                # Each processed event should have a full URL stored in the mapping
                raise ValueError(
                    f"Full URL not found for event_id {event_id} when summarizing session_id {session_id}: {event_mapping_data}"
                )
            enriched_event["current_url"] = full_current_url
            # Add window ID of the event
            window_id = event_mapping_data[window_id_index]
            full_window_id = window_mapping_reversed.get(window_id)
            if not full_window_id:
                # Each processed event should have a full window ID stored in the mapping
                raise ValueError(
                    f"Full window ID not found for event_id {event_id} when summarizing session_id {session_id}: {event_mapping_data}"
                )
            enriched_event["window_id"] = full_window_id
            # Add event type (if applicable)
            event_type = event_mapping_data[event_type_index]
            if event_type:
                enriched_event["event_type"] = event_type
            # Add event index to better link summary event with an actual event
            enriched_event["event_index"] = event_mapping_data[event_index_index]
            enriched_events.append(enriched_event)
        # Ensure chronological order of the events
        enriched_events.sort(key=lambda x: x.get("milliseconds_since_start", 0))
        enriched_key_actions.append({"objective": objective, "events": enriched_events})
    # Validate the enriched content against the schema
    summary_to_enrich = dict(raw_session_summary.data)
    summary_to_enrich["key_actions"] = enriched_key_actions
    session_summary = _validate_enriched_summary(summary_to_enrich, session_id)
    return session_summary
