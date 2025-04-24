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
        raise ValueError(f"No session metadata found for session_id {session_id}")
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


def _skip_event_without_context(
    event_row: list[str | datetime, ...],
    # Using indexes as argument to avoid calling get_column_index on each event row
    indexes: dict[str, int],
) -> bool:
    """
    Avoid events that don't add meaningful context and confuse the LLM.
    """
    event = event_row[indexes["event"]]
    elements_chain_texts = event_row[indexes["elements_chain_texts"]]
    elements_chain_elements = event_row[indexes["elements_chain_elements"]]
    elements_chain_href = event_row[indexes["elements_chain_href"]]
    elements_chain_ids = event_row[indexes["elements_chain_ids"]]
    # Skip autocapture events with no proper context
    if event == "$autocapture":
        if (
            not elements_chain_texts
            and not elements_chain_elements
            and not elements_chain_href
            and not elements_chain_ids
        ):
            return True
    # Skip custom events with no proper context
    # Assuming that events with a short name and no contexts aren't useful for the summary
    # TODO: Check the assumptions, as could be risky, but worth it to avoid adding noise
    if (
        not event.startswith("$")
        and len(event.split(" ")) == 1
        and len(event.split(".")) == 1
        and len(event.split("_")) == 1
    ):
        if (
            not elements_chain_texts
            and not elements_chain_elements
            and not elements_chain_href
            and not elements_chain_ids
        ):
            return True
    return False


def add_context_and_filter_events(
    session_events_columns: list[str], session_events: list[tuple[str | datetime, ...]]
) -> tuple[list[str], list[tuple[str | datetime, ...]]]:
    indexes = {
        "event": get_column_index(session_events_columns, "event"),
        "$event_type": get_column_index(session_events_columns, "$event_type"),
        "elements_chain": get_column_index(session_events_columns, "elements_chain"),
        "elements_chain_texts": get_column_index(session_events_columns, "elements_chain_texts"),
        "elements_chain_elements": get_column_index(session_events_columns, "elements_chain_elements"),
        "elements_chain_href": get_column_index(session_events_columns, "elements_chain_href"),
        "elements_chain_ids": get_column_index(session_events_columns, "elements_chain_ids"),
    }
    updated_events = []
    for event in session_events:
        chain = event[indexes["elements_chain"]]
        if not chain:
            # If no chain - no additional context will come, so it's ok to check if to skip right away
            if _skip_event_without_context(event, indexes):
                continue
            updated_event = list(event)
            updated_event.pop(indexes["elements_chain"])
            updated_events.append(tuple(updated_event))
            continue
        updated_event = list(event)
        updated_event[indexes["elements_chain_texts"]] = _get_improved_elements_chain_texts(
            chain, event[indexes["elements_chain_texts"]]
        )
        updated_event[indexes["elements_chain_elements"]] = _get_improved_elements_chain_elements(
            chain, event[indexes["elements_chain_elements"]]
        )
        # After additional context is added, check again if the event is still without context
        if _skip_event_without_context(updated_event, indexes):
            continue
        # Remove chain from as we already got all the info from it (safe to remove as it's the last column)
        updated_event.pop(indexes["elements_chain"])
        updated_events.append(tuple(updated_event))
    # Remove chain from columns also to avoid confusion (safe to remove as it's the last column)
    updated_columns = session_events_columns.copy()
    updated_columns.pop(indexes["elements_chain"])
    return updated_columns, updated_events


def _get_improved_elements_chain_texts(elements_chain: str, current_texts: list[str]) -> list[str]:
    """
    Get additional text from element chain (instead of default "text") for better context
    """
    raw_texts = re.findall(r'(?::|\")(?:text|attr__aria-label)="\"?(.*?)\"?"', elements_chain)
    # Remove duplicates
    texts = list(dict.fromkeys(raw_texts))
    if not texts and not current_texts:
        return []
    # If the current texts are longer, avoid modifications, as the goal to have as much context as possible
    if len(current_texts) > len(texts):
        return current_texts
    return texts


def _get_improved_elements_chain_elements(elements_chain: str, current_elements: list[str]) -> list[str]:
    """
    Attach type to elements (if found) for better context
    """
    raw_updated_elements = []
    raw_element_blocks = re.findall(
        r"(?:^|;)(a|button|form|input|select|textarea|label)\.?(.*?)(?=;|$)", elements_chain
    )
    for element, context in raw_element_blocks:
        element_type = re.findall(r'(?::|\")attr__type="\"?(.*?)\"?"', context)
        # If no type found
        if not element_type:
            raw_updated_elements.append(element)
            continue
        # Button type doesn't add any new context
        if element_type[0] == "button":
            raw_updated_elements.append(element)
            continue
        raw_updated_elements.append(f'{element}[type="{element_type[0]}"]')
    # Remove duplicates
    updated_elements = list(dict.fromkeys(raw_updated_elements))
    if not updated_elements and not current_elements:
        return []
    # If the current elements are longer, avoid modifications, as the goal to have as much context as possible
    if len(current_elements) > len(updated_elements):
        return current_elements
    return updated_elements
