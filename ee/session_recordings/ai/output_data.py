from datetime import datetime
from typing import Any
from rest_framework import serializers
from openai.types.chat.chat_completion import ChatCompletion
import yaml

from ee.session_recordings.session_summary.utils import get_column_index


class EventTagSerializer(serializers.Serializer):
    where = serializers.ListField(child=serializers.CharField(min_length=1, max_length=256), allow_empty=False)
    what = serializers.ListField(child=serializers.CharField(min_length=1, max_length=256), allow_empty=False)


class BaseKeyEventSerializer(serializers.Serializer):
    description = serializers.CharField(min_length=1, max_length=1024)
    error = serializers.BooleanField()
    tags = EventTagSerializer()


class RawKeyEventSerializer(BaseKeyEventSerializer):
    """
    Events coming from LLM.
    """

    event_id = serializers.CharField(min_length=1, max_length=128)


class KeyEventSerializer(BaseKeyEventSerializer):
    """
    LLM events enriched with metadata.
    """

    timestamp = serializers.CharField(max_length=128)
    milliseconds_since_start = serializers.IntegerField(min_value=0)
    window_id = serializers.CharField(max_length=128, required=False, allow_null=True)
    current_url = serializers.CharField(min_length=1)
    event = serializers.CharField(min_length=1, max_length=128)
    event_type = serializers.CharField(max_length=128, required=False, allow_null=True)


class RawSessionSummarySerializer(serializers.Serializer):
    """
    Raw session summary coming from LLM.
    """

    summary = serializers.CharField(min_length=1, max_length=2048)
    key_events = serializers.ListField(child=RawKeyEventSerializer(), allow_empty=False)


class SessionSummarySerializer(serializers.Serializer):
    """
    Session summary enriched with metadata.
    """

    summary = serializers.CharField(min_length=1, max_length=2048)
    key_events = serializers.ListField(child=KeyEventSerializer(), allow_empty=False)


def load_raw_session_summary_from_llm_content(
    llm_response: ChatCompletion, allowed_event_ids: list[str], session_id: str
) -> RawSessionSummarySerializer:
    raw_content: str = llm_response.choices[0].message.content
    if not raw_content:
        raise ValueError(f"No LLM content found when summarizing session_id {session_id}: {llm_response}")
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
    for key_event in raw_session_summary.data["key_events"]:
        event_id = key_event.get("event_id")
        if not event_id:
            raise ValueError(
                f"LLM returned event without event_id when summarizing session_id {session_id}: {raw_session_summary.data}"
            )
        if key_event["event_id"] not in allowed_event_ids:
            raise ValueError(
                f"LLM hallucinated event_id {event_id} when summarizing session_id "
                f"{session_id} (not in allowed events: {allowed_event_ids}): {raw_session_summary.data}"
            )
    return raw_session_summary


def _calculate_time_since_start(session_timestamp: str, session_start_time: datetime | None) -> int | None:
    if not session_start_time or not session_timestamp:
        return None
    timestamp_datetime = datetime.fromisoformat(session_timestamp)
    return int((timestamp_datetime - session_start_time).total_seconds() * 1000)


def enrich_raw_session_summary_with_events_meta(
    raw_session_summary: RawSessionSummarySerializer,
    simplified_events_mapping: dict[str, list[Any]],
    simplified_events_columns: list[str],
    url_mapping_reversed: dict[str, str],
    window_mapping_reversed: dict[str, str],
    session_start_time: datetime | None,
    session_id: str,
) -> SessionSummarySerializer:
    timestamp_index = get_column_index(simplified_events_columns, "timestamp")
    window_id_index = get_column_index(simplified_events_columns, "$window_id")
    current_url_index = get_column_index(simplified_events_columns, "$current_url")
    event_index = get_column_index(simplified_events_columns, "event")
    event_type_index = get_column_index(simplified_events_columns, "$event_type")
    enriched_key_events = []
    # Enrich LLM events with metadata
    for key_event in raw_session_summary.data["key_events"]:
        event_id = key_event["event_id"]
        enriched_key_event = dict(key_event)
        enriched_key_event["event"] = simplified_events_mapping[event_id][event_index]
        # Calculate time to jump to the right place in the player
        timestamp = simplified_events_mapping[event_id][timestamp_index]
        enriched_key_event["timestamp"] = timestamp
        ms_since_start = _calculate_time_since_start(timestamp, session_start_time)
        if ms_since_start:
            enriched_key_event["milliseconds_since_start"] = ms_since_start
        # Add full URL of the event page
        current_url = simplified_events_mapping[event_id][current_url_index]
        full_current_url = current_url and url_mapping_reversed.get(current_url)
        if full_current_url:
            enriched_key_event["current_url"] = full_current_url
        # Add window ID of the event
        window_id = simplified_events_mapping[event_id][window_id_index]
        full_window_id = window_id and window_mapping_reversed.get(window_id)
        if full_window_id:
            enriched_key_event["window_id"] = full_window_id
        # Add event type (if applicable)
        event_type = simplified_events_mapping[event_id][event_type_index]
        if event_type:
            enriched_key_event["event_type"] = event_type
        enriched_key_events.append(enriched_key_event)
    # Ensure chronolical order of the events
    enriched_key_events.sort(key=lambda x: x["milliseconds_since_start"])
    # Validate the enriched content against the schema
    summary_to_enrich = dict(raw_session_summary.data)
    summary_to_enrich["key_events"] = enriched_key_events
    session_summary = SessionSummarySerializer(data=summary_to_enrich)
    if not session_summary.is_valid():
        raise ValueError(
            f"Error validating enriched content against the schema when summarizing session_id {session_id}: {session_summary.errors}"
        )
    return session_summary
