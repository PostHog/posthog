from datetime import datetime
import re
from typing import cast

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
        raw_session_metadata = load_session_metadata_from_json(local_path)
        session_metadata = cast(RecordingMetadata, raw_session_metadata)
    if not session_metadata:
        raise ValueError(f"No session metadata found for session_id {session_id}")
    return session_metadata


def _get_paginated_session_events(
    session_id: str,
    session_metadata: RecordingMetadata,
    team: Team,
    max_pages: int,
    items_per_page: int,
    events_to_ignore: list[str] | None = None,
    extra_fields: list[str] | None = None,
) -> tuple[list[str], list[tuple[str | datetime | list[str] | None, ...]]]:
    """
    Get session events with pagination to handle large sessions.
    Returns combined results from all pages up to max_pages.
    """
    all_events = []
    columns = None
    events_obj = SessionReplayEvents()
    for page in range(max_pages):
        page_columns, page_events = events_obj.get_events(
            session_id=str(session_id),
            team=team,
            metadata=session_metadata,
            events_to_ignore=events_to_ignore,
            extra_fields=extra_fields,
            limit=items_per_page,
            page=page,
        )
        # Expect columns to be exact for all the page as we don't change the query
        if page_columns and not columns:
            columns = page_columns
        # Avoid the next page if no events are returned
        if not page_events:
            break
        all_events.extend(page_events)
        # Or we got less than the page size (reached the end)
        if len(page_events) < items_per_page:
            break
    if not columns or not all_events:
        raise ValueError(f"No events found for session_id {session_id}")
    return columns, all_events


def get_session_events(
    session_id: str,
    session_metadata: RecordingMetadata,
    team: Team,
    local_path: str | None = None,
    # The estimation that we can cover 2 hours/3000 events per page within 200 000 token window,
    # but as GPT-4.1 allows up to 1kk tokens, we can allow up to 4 hours sessions to be covered
    # TODO: Check if it's a meaningful approach, or should we just analyze firt N events for huge sessions
    # TODO: Move to a config
    max_pages: int = 2,
    items_per_page: int = 3000,
) -> tuple[list[str], list[tuple[str | datetime | list[str] | None, ...]]]:
    if not local_path:
        return _get_paginated_session_events(
            session_id=str(session_id),
            team=team,
            session_metadata=session_metadata,
            max_pages=max_pages,
            items_per_page=items_per_page,
            events_to_ignore=["$feature_flag_called"],
            extra_fields=EXTRA_SUMMARY_EVENT_FIELDS,
        )
    else:
        session_events_columns, session_events = load_session_recording_events_from_csv(
            local_path, extra_fields=EXTRA_SUMMARY_EVENT_FIELDS
        )
    if not session_events_columns or not session_events:
        raise ValueError(f"No events found for session_id {session_id}")
    return session_events_columns, session_events


def _skip_event_without_context(
    event_row: list[str | datetime | list[str] | None],
    # Using indexes as argument to avoid calling get_column_index on each event row
    indexes: dict[str, int],
) -> bool:
    """
    Avoid events that don't add meaningful context and confuse the LLM.
    # TODO: Check the assumptions, as could be risky, but worth it to avoid adding noise
    """
    event = cast(str, event_row[indexes["event"]])
    elements_chain_texts = event_row[indexes["elements_chain_texts"]]
    elements_chain_elements = event_row[indexes["elements_chain_elements"]]
    elements_chain_href = event_row[indexes["elements_chain_href"]]
    elements_chain_ids = event_row[indexes["elements_chain_ids"]]
    # Never skip events with descriptive names
    if len(event.split(" ")) > 1 or len(event.split(".")) > 1 or len(event.split("_")) > 1:
        return False
    # Keep events with at least some context
    if elements_chain_texts or elements_chain_elements or elements_chain_href or elements_chain_ids:
        return False
    # Never skip system events (except empty autocapture)
    if event.startswith("$") and event != "$autocapture":
        return False
    # Skip all remaining non-system events with short names and no context
    # TODO: Add local only logging to check what events are being skipped,
    # as the events structure changes from client to client
    return True


def add_context_and_filter_events(
    session_events_columns: list[str], session_events: list[tuple[str | datetime | list[str] | None, ...]]
) -> tuple[list[str], list[tuple[str | datetime | list[str] | None, ...]]]:
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
        if not isinstance(chain, str):
            raise ValueError(f"Elements chain is not a string: {chain}")
        updated_event: list[str | datetime | list[str] | None] = list(event)
        if not chain:
            # If no chain - no additional context will come, so it's ok to check if to skip right away
            if _skip_event_without_context(updated_event, indexes):
                continue
            updated_event.pop(indexes["elements_chain"])
            updated_events.append(tuple(updated_event))
            continue
        elements_chain_texts = event[indexes["elements_chain_texts"]]
        if not isinstance(elements_chain_texts, list):
            raise ValueError(f"Elements chain texts is not a list: {elements_chain_texts}")
        updated_event[indexes["elements_chain_texts"]] = _get_improved_elements_chain_texts(chain, elements_chain_texts)
        elements_chain_elements = event[indexes["elements_chain_elements"]]
        if not isinstance(elements_chain_elements, list):
            raise ValueError(f"Elements chain elements is not a list: {elements_chain_elements}")
        updated_event[indexes["elements_chain_elements"]] = _get_improved_elements_chain_elements(
            chain, elements_chain_elements
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
