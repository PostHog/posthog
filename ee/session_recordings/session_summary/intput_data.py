from datetime import datetime
import re

from ee.session_recordings.session_summary.utils import (
    get_column_index,
    load_session_metadata_from_json,
    load_session_recording_events_from_csv,
)
from posthog.session_recordings.models.metadata import RecordingMetadata
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.models import Team

EXTRA_SUMMARY_EVENT_FIELDS = ["elements_chain_ids", "elements_chain"]


def get_session_metadata(session_id: str, team: Team, local_path: str | None = None) -> RecordingMetadata:
    if not local_path:
        session_metadata = SessionReplayEvents().get_metadata(session_id=str(session_id), team=team)
    else:
        session_metadata = load_session_metadata_from_json(local_path)
    if not session_metadata:
        raise ValueError(f"no session metadata found for session_id {session_id}")
    return session_metadata


def get_session_events(
    session_id: str, session_metadata: RecordingMetadata, team: Team, local_path: str | None = None
) -> tuple[list[str], list[tuple[str | datetime, ...]]]:
    if not local_path:
        session_events_columns, session_events = SessionReplayEvents().get_events(
            session_id=str(session_id),
            team=team,
            metadata=session_metadata,
            events_to_ignore=[
                "$feature_flag_called",
            ],
            extra_fields=EXTRA_SUMMARY_EVENT_FIELDS,
        )
    else:
        session_events_columns, session_events = load_session_recording_events_from_csv(
            local_path, extra_fields=EXTRA_SUMMARY_EVENT_FIELDS
        )
    if not session_events_columns or not session_events:
        raise ValueError(f"no events found for session_id {session_id}")
    return session_events_columns, session_events


def load_additional_event_context_from_elements_chain(
    session_events_columns: list[str], session_events: list[tuple[str | datetime, ...]]
) -> list[tuple[str | datetime, ...]]:
    chain_index = get_column_index(session_events_columns, "elements_chain")
    chain_texts_index = get_column_index(session_events_columns, "elements_chain_texts")
    # chain_elements_index = get_column_index(session_events_columns, "elements_chain_elements")
    # chain_ids_index = get_column_index(session_events_columns, "elements_chain_ids")
    updated_events = []
    for event in session_events:
        updated_event = list(event)
        chain = event[chain_index]
        improved_chain_texts = _get_improved_elements_chain_texts(chain, event[chain_texts_index])
        updated_event[chain_texts_index] = improved_chain_texts
        updated_events.append(tuple(updated_event))
    return updated_events


def _filter_repeated_elements(elements: list[str]) -> list[str]:
    # Keep unique elements keeping the order
    return list(dict.fromkeys(elements))


def _get_improved_elements_chain_texts(elements_chain: str, current_texts: list[str]) -> list[str]:
    raw_texts = re.findall(r'(?::|\")(?:text|attr__aria-label)="\"?(.*?)\"?"', elements_chain)
    texts = _filter_repeated_elements(raw_texts)
    if not texts and not current_texts:
        return []
    # If the current texts are longer, avoid modifications, as the goal to have as much context as possible
    if len(current_texts) > len(texts):
        return current_texts
    return texts
