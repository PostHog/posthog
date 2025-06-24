import datetime
import json
import re
from typing import cast

from ee.session_recordings.session_summary.local.input_data import (
    _get_production_session_events_locally,
    _get_production_session_metadata_locally,
)
from ee.session_recordings.session_summary.utils import (
    get_column_index,
)
from posthog.session_recordings.models.metadata import RecordingMetadata
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.models import Team

EXTRA_SUMMARY_EVENT_FIELDS = [
    "elements_chain_ids",
    "elements_chain",
    "properties.$exception_types",
    "properties.$exception_sources",
    "properties.$exception_values",
    "properties.$exception_fingerprint_record",
    "properties.$exception_functions",
]
# Columns that are useful to building context or/and filtering, but would be excessive for the LLM
COLUMNS_TO_REMOVE_FROM_LLM_CONTEXT = [
    "elements_chain",
    "$exception_sources",
    "$exception_fingerprint_record",
    "$exception_functions",
]


def get_team(team_id: int) -> Team:
    return Team.objects.get(id=team_id)


def get_session_metadata(session_id: str, team_id: int, local_reads_prod: bool = False) -> RecordingMetadata:
    events_obj = SessionReplayEvents()
    if not local_reads_prod:
        session_metadata = events_obj.get_metadata(session_id=str(session_id), team_id=team_id)
    else:
        session_metadata = _get_production_session_metadata_locally(events_obj, session_id, team_id)
    if not session_metadata:
        raise ValueError(f"No session metadata found for session_id {session_id}")
    return session_metadata


def get_session_events(
    session_id: str,
    session_metadata: RecordingMetadata,
    team_id: int,
    local_reads_prod: bool = False,
    # The estimation that we can cover 2 hours/3000 events per page within 200 000 token window,
    # but as GPT-4.1 allows up to 1kk tokens, we can allow up to 4 hours sessions to be covered
    # TODO: Check if it's a meaningful approach, or should we just analyze first N events for huge sessions
    # TODO: Move to a config
    max_pages: int = 2,
    items_per_page: int = 3000,
) -> tuple[list[str], list[tuple[str | datetime.datetime | list[str] | None, ...]]]:
    """
    Get session events with pagination to handle large sessions.
    Returns combined results from all pages up to max_pages.
    """
    events_to_ignore = ["$feature_flag_called"]
    extra_fields = EXTRA_SUMMARY_EVENT_FIELDS
    # Collect all events and columns from all pages
    all_events = []
    columns = None
    events_obj = SessionReplayEvents()
    for page in range(max_pages):
        if not local_reads_prod:
            team = get_team(team_id=team_id)
            page_columns, page_events = events_obj.get_events(
                session_id=str(session_id),
                team=team,
                metadata=session_metadata,
                events_to_ignore=events_to_ignore,
                extra_fields=extra_fields,
                limit=items_per_page,
                page=page,
            )
        else:
            page_columns, page_events = _get_production_session_events_locally(
                events_obj=events_obj,
                session_id=str(session_id),
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
    if not columns:
        raise ValueError(f"No columns found for session_id {session_id}")
    if not all_events:
        # Raise an error only if there were no events on all pages,
        # to avoid false positives when the first page consumed all events precisely
        raise ValueError(f"No events found for session_id {session_id}")
    return columns, all_events


def _skip_exception_without_valid_context(
    event_row: list[str | datetime.datetime | list[str] | None],
    # Using indexes as argument to avoid calling get_column_index on each event row
    indexes: dict[str, int],
) -> bool:
    """
    Avoid exceptions that don't add meaningful context and confuse the LLM.
    """

    def load_json_list(row, indexes, key):
        raw_list = row[indexes[key]]
        try:
            json_list = json.loads(raw_list)
            if not json_list or not isinstance(json_list, list):
                return []
            return json_list
        except Exception:
            return []

    exception_sources = load_json_list(event_row, indexes, "$exception_sources")
    exception_values = load_json_list(event_row, indexes, "$exception_values")
    exception_fingerprint_record = load_json_list(event_row, indexes, "$exception_fingerprint_record")
    exception_functions = load_json_list(event_row, indexes, "$exception_functions")
    # Keep exceptions with 5+ traces as blocking errors usually affect multiple flows
    if len(exception_fingerprint_record) >= 5:
        return False
    # Search for keywords in functions names to try to catch API errors (that are usually blocking).
    # Matching .* to also catch the usage in the middle of the filename or function. Ensure to ignore letter case.
    pattern = (
        r".*(api|http|fetch|request|post|put|delete|response|xhr|ajax|graphql|socket|websocket|auth|token|login).*"
    )
    if exception_functions and any(re.search(pattern, fn, re.IGNORECASE) for fn in exception_functions):
        return False
    # Search for the same keywords in filenames, if applicable
    if exception_sources and any(re.search(pattern, source, re.IGNORECASE) for source in exception_sources):
        return False
    # Search for the same keywords in values, if applicable
    if exception_values and any(re.search(pattern, value, re.IGNORECASE) for value in exception_values):
        return False
    # Filter out all the rest
    return True


def _skip_event_without_valid_context(
    event_row: list[str | datetime.datetime | list[str] | None],
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
    session_events_columns: list[str], session_events: list[tuple[str | datetime.datetime | list[str] | None, ...]]
) -> tuple[list[str], list[tuple[str | datetime.datetime | list[str] | None, ...]]]:
    indexes = {
        "event": get_column_index(session_events_columns, "event"),
        "$event_type": get_column_index(session_events_columns, "$event_type"),
        "elements_chain_texts": get_column_index(session_events_columns, "elements_chain_texts"),
        "elements_chain_elements": get_column_index(session_events_columns, "elements_chain_elements"),
        "elements_chain_href": get_column_index(session_events_columns, "elements_chain_href"),
        "elements_chain_ids": get_column_index(session_events_columns, "elements_chain_ids"),
        "elements_chain": get_column_index(session_events_columns, "elements_chain"),
        "$exception_types": get_column_index(session_events_columns, "$exception_types"),
        "$exception_values": get_column_index(session_events_columns, "$exception_values"),
        "$exception_sources": get_column_index(session_events_columns, "$exception_sources"),
        "$exception_fingerprint_record": get_column_index(session_events_columns, "$exception_fingerprint_record"),
        "$exception_functions": get_column_index(session_events_columns, "$exception_functions"),
    }
    # Columns to go into the LLM
    columns_to_keep = [
        i for i, col in enumerate(session_events_columns) if col not in COLUMNS_TO_REMOVE_FROM_LLM_CONTEXT
    ]
    updated_events = []
    for event in session_events:
        updated_event: list[str | datetime.datetime | list[str] | None] = list(event)
        # Check for errors worth keeping in the context
        if event[indexes["event"]] == "$exception":
            if _skip_exception_without_valid_context(updated_event, indexes):
                continue
            # If it's a valid exception, there are no elements to enrich the context, so keep it as is
            updated_events.append(tuple(updated_event[i] for i in columns_to_keep))
            continue
        chain = event[indexes["elements_chain"]]
        if not isinstance(chain, str):
            raise ValueError(f"Elements chain is not a string: {chain}")
        if not chain:
            # If no chain - no additional context will come, so it's ok to check if to skip right away
            if _skip_event_without_valid_context(updated_event, indexes):
                continue
            updated_events.append(tuple(updated_event[i] for i in columns_to_keep))
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
        if _skip_event_without_valid_context(updated_event, indexes):
            continue
        updated_events.append(tuple(updated_event[i] for i in columns_to_keep))
    updated_columns = [session_events_columns[i] for i in columns_to_keep]
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
