from datetime import datetime
from typing import Any
from rest_framework import serializers
from openai.types.chat.chat_completion import ChatCompletion
import yaml

from ee.session_recordings.session_summary.utils import get_column_index


class BaseKeyActionSerializer(serializers.Serializer):
    description = serializers.CharField(min_length=1, max_length=1024)
    error = serializers.BooleanField()
    event_id = serializers.CharField(min_length=1, max_length=128)


class EnrichedKeyActionSerializer(BaseKeyActionSerializer):
    """
    LLM actions enriched with metadata.
    """

    timestamp = serializers.CharField(max_length=128)
    milliseconds_since_start = serializers.IntegerField(min_value=0)
    window_id = serializers.CharField(max_length=128, required=False, allow_null=True)
    current_url = serializers.CharField(min_length=1)
    event = serializers.CharField(min_length=1, max_length=128)
    event_type = serializers.CharField(max_length=128, required=False, allow_null=True)
    event_index = serializers.IntegerField(min_value=0)


class RawObjectiveSerializer(serializers.Serializer):
    """
    Objectives coming from LLM.
    """

    name = serializers.CharField(min_length=1, max_length=256)
    summary = serializers.CharField(min_length=1, max_length=1024)
    key_actions = serializers.ListField(child=BaseKeyActionSerializer(), allow_empty=False)


class EnrichedObjectiveSerializer(RawObjectiveSerializer):
    """
    Objectives enriched with metadata.
    """

    key_actions = serializers.ListField(child=EnrichedKeyActionSerializer(), allow_empty=False)


class RawSessionSummarySerializer(serializers.Serializer):
    """
    Raw session summary coming from LLM.
    """

    objectives = serializers.ListField(child=RawObjectiveSerializer(), allow_empty=False)
    initial_goal = serializers.CharField(min_length=1, max_length=1024)
    session_outcome = serializers.CharField(min_length=1, max_length=1024)


class SessionSummarySerializer(serializers.Serializer):
    """
    Session summary enriched with metadata.
    """

    objectives = serializers.ListField(child=EnrichedObjectiveSerializer(), allow_empty=False)
    initial_goal = serializers.CharField(min_length=1, max_length=1024)
    session_outcome = serializers.CharField(min_length=1, max_length=1024)


def load_raw_session_summary_from_llm_content(
    llm_response: ChatCompletion, allowed_event_ids: list[str], session_id: str
) -> RawSessionSummarySerializer:
    if not llm_response.choices or not llm_response.choices[0].message or not llm_response.choices[0].message.content:
        raise ValueError(f"No LLM content found when summarizing session_id {session_id}: {llm_response}")
    raw_content: str = llm_response.choices[0].message.content
    try:
        # Strip the first and the last line of the content to load the YAML data only into JSON
        # TODO Work on a more robust solution
        json_content: dict = yaml.safe_load(raw_content.strip("```yaml\n").strip("```").strip())  # noqa: B005
    except Exception as e:
        raise ValueError(f"Error loading YAML content into JSON when summarizing session_id {session_id}: {e}")
    # Validate the LLM output against the schema
    raw_session_summary = RawSessionSummarySerializer(data=json_content)
    if not raw_session_summary.is_valid():
        raise ValueError(
            f"Error validating LLM output against the schema when summarizing session_id {session_id}: {raw_session_summary.errors}"
        )
    # Ensure that LLM didn't hallucinate events
    for objective in raw_session_summary.data["objectives"]:
        for key_action in objective["key_actions"]:
            event_id = key_action["event_id"]
            if not event_id:
                raise ValueError(
                    f"LLM returned event without event_id when summarizing session_id {session_id}: {raw_session_summary.data}"
                )
            # TODO: Allow skipping some events (even if not too many to speed up the process
            if key_action["event_id"] not in allowed_event_ids:
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
    enriched_objectives = []
    # Enrich LLM events with metadata
    for objective in raw_session_summary.data["objectives"]:
        enriched_objective = dict(objective)
        enriched_key_actions = []
        for key_action in objective["key_actions"]:
            event_id: str | None = key_action.get("event_id")
            if not event_id:
                raise ValueError(
                    f"LLM returned event without event_id when summarizing session_id {session_id}: {raw_session_summary}"
                )
            enriched_key_action = dict(key_action)
            event_mapping_data = simplified_events_mapping.get(event_id)
            if not event_mapping_data:
                raise ValueError(
                    f"Mapping data for event_id {event_id} not found when summarizing session_id {session_id}: {raw_session_summary}"
                )
            enriched_key_action["event"] = event_mapping_data[event_index]
            # Calculate time to jump to the right place in the player
            timestamp = event_mapping_data[timestamp_index]
            enriched_key_action["timestamp"] = timestamp
            ms_since_start = calculate_time_since_start(timestamp, session_start_time)
            if ms_since_start is not None:
                enriched_key_action["milliseconds_since_start"] = ms_since_start
            # Add full URL of the event page
            current_url = event_mapping_data[current_url_index]
            if not current_url:
                raise ValueError(
                    f"Current URL not found for event_id {event_id} when summarizing session_id {session_id}: {event_mapping_data}"
                )
            full_current_url = current_url and url_mapping_reversed.get(current_url)
            if full_current_url:
                enriched_key_action["current_url"] = full_current_url
            # Add window ID of the event
            window_id = event_mapping_data[window_id_index]
            full_window_id = window_id and window_mapping_reversed.get(window_id)
            if full_window_id:
                enriched_key_action["window_id"] = full_window_id
            # Add event type (if applicable)
            event_type = event_mapping_data[event_type_index]
            if event_type:
                enriched_key_action["event_type"] = event_type
            # Add event index to better link summary event with an actual event
            enriched_key_action["event_index"] = event_mapping_data[event_index_index]
            enriched_key_actions.append(enriched_key_action)
        # Ensure chronological order of the events
        enriched_key_actions.sort(key=lambda x: x["milliseconds_since_start"])
        enriched_objective["key_actions"] = enriched_key_actions
        enriched_objectives.append(enriched_objective)
    # Validate the enriched content against the schema
    summary_to_enrich = dict(raw_session_summary.data)
    summary_to_enrich["objectives"] = enriched_objectives
    session_summary = SessionSummarySerializer(data=summary_to_enrich)
    if not session_summary.is_valid():
        raise ValueError(
            f"Error validating enriched content against the schema when summarizing session_id {session_id}: {session_summary.errors}"
        )
    return session_summary
