from typing import Any, Optional

from prometheus_client import Counter
from pydantic import ValidationError
from structlog import get_logger

from posthog.schema import (
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingPropertyFilter,
    RecordingsQuery,
)

from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.utils import filter_from_params_to_query

logger = get_logger(__name__)

REPLAY_PLAYLIST_LEGACY_FILTERS_CONVERTED = Counter(
    "replay_playlist_legacy_filters_converted",
    "when a count task for a playlist converts legacy filters to universal filters",
)

DEFAULT_RECORDING_FILTERS = {
    "date_from": "-3d",
    "date_to": None,
    "filter_test_accounts": False,
    "duration": [
        {
            "type": PropertyFilterType.RECORDING,
            "key": "active_seconds",
            "value": 5,
            "operator": PropertyOperator.GT,
        }
    ],
    "order": "start_time",
}


def asRecordingPropertyFilter(filter: dict[str, Any]) -> RecordingPropertyFilter:
    return RecordingPropertyFilter(
        key=filter["key"],
        operator=filter["operator"],
        value=filter["value"],
    )


def _flatten_filter_group_values(values: Optional[list[Any]]) -> list[dict[str, Any]]:
    """Recursively flatten nested universal-filter groups into their leaf filters.

    Mirrors the frontend's filtersFromUniversalFilterGroups — a single-level read misses
    filters nested under inner groups (and saved filters do nest them).
    """
    leaves: list[dict[str, Any]] = []
    for item in values or []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("values"), list):
            leaves.extend(_flatten_filter_group_values(item["values"]))
        else:
            leaves.append(item)
    return leaves


def _derive_operand(filter_group: Optional[dict[str, Any]]) -> FilterLogicalOperator:
    """Treat the query as OR when any group in the tree is OR.

    The "match any" operand can sit on the inner group (set via the nested-group editor) while
    the outer group stays AND. Reading only the outer group would silently drop that intent, so
    mirror the frontend's deriveOperand and let OR anywhere in the tree win.
    """
    if not isinstance(filter_group, dict):
        return FilterLogicalOperator.AND_
    if filter_group.get("type") == FilterLogicalOperator.OR_:
        return FilterLogicalOperator.OR_
    if any(
        isinstance(value, dict)
        and isinstance(value.get("values"), list)
        and _derive_operand(value) == FilterLogicalOperator.OR_
        for value in filter_group.get("values") or []
    ):
        return FilterLogicalOperator.OR_
    return FilterLogicalOperator.AND_


def convert_legacy_filters_to_universal_filters(filters: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """
    Convert legacy filters to universal filters format.
    This is the Python equivalent of the frontend's convertLegacyFiltersToUniversalFilters function.
    """
    filters = filters or {}

    if not filters:
        return {}

    events = filters.get("events", [])
    actions = filters.get("actions", [])
    properties = filters.get("properties", [])

    log_level_filters = []
    if filters.get("console_logs"):
        log_level_filters.append(
            {
                "key": "level",
                "value": filters["console_logs"],
                "operator": PropertyOperator.EXACT,
                "type": PropertyFilterType.LOG_ENTRY,
            }
        )

    log_query_filters = []
    if filters.get("console_search_query"):
        log_query_filters.append(
            {
                "key": "message",
                "value": [filters["console_search_query"]],
                "operator": PropertyOperator.EXACT,
                "type": PropertyFilterType.LOG_ENTRY,
            }
        )

    duration = []
    if filters.get("session_recording_duration"):
        duration.append(
            {
                **filters["session_recording_duration"],
                "key": filters.get(
                    "duration_type_filter", filters.get("session_recording_duration", {}).get("key", "active_seconds")
                ),
            }
        )

    return {
        "date_from": filters.get("date_from") or DEFAULT_RECORDING_FILTERS["date_from"],
        "date_to": filters.get("date_to") or DEFAULT_RECORDING_FILTERS["date_to"],
        "filter_test_accounts": filters.get("filter_test_accounts", DEFAULT_RECORDING_FILTERS["filter_test_accounts"]),
        "duration": duration or DEFAULT_RECORDING_FILTERS["duration"],
        "filter_group": {
            "type": FilterLogicalOperator.AND_,
            "values": [
                {
                    "type": FilterLogicalOperator.AND_,
                    "values": events + actions + properties + log_level_filters + log_query_filters,
                }
            ],
        },
        "order": DEFAULT_RECORDING_FILTERS["order"],
    }


def convert_playlist_to_recordings_query(
    playlist: SessionRecordingPlaylist, *, persist_legacy_conversion: bool = True
) -> RecordingsQuery:
    """Convert playlist with filters to a RecordingsQuery object.

    When ``persist_legacy_conversion`` is False the legacy->universal conversion happens
    in-memory only — callers on a read path (e.g. rendering a dashboard widget) should not
    write to the shared playlist row as a side effect.
    """
    # Copy so the popping below never mutates the shared playlist.filters dict in-place.
    filters = dict(playlist.filters)

    # we used to send `version` and it's not part of query, so we pop to make sure
    filters.pop("version", None)
    # we used to send `hogql_filtering` and it's not part of query, so we pop to make sure
    filters.pop("hogql_filtering", None)

    # Check if we have legacy filters (they don't have filter_group)
    if "filter_group" not in filters:
        if not filters:
            return filter_from_params_to_query(filters)
        else:
            # then we have a legacy filter
            # because we know we don't have a query
            filters = convert_legacy_filters_to_universal_filters(filters)
            if persist_legacy_conversion:
                playlist.filters = filters
                playlist.save(update_fields=["filters"])
                REPLAY_PLAYLIST_LEGACY_FILTERS_CONVERTED.inc()

    return convert_filters_to_recordings_query(filters)


def convert_filters_to_recordings_query(filters: dict[str, Any]) -> RecordingsQuery:
    """
    Convert universal filters to a RecordingsQuery object.
    This is the Python equivalent of the frontend's convertUniversalFiltersToRecordingsQuery function.
    """

    extracted_filters = _flatten_filter_group_values((filters.get("filter_group") or {}).get("values"))

    # Heterogeneous builder lists — each holds raw filter dicts and/or RecordingPropertyFilter
    # objects that RecordingsQuery accepts via its property-filter unions.
    events: list[Any] = []
    actions: list[Any] = []
    properties: list[Any] = []
    console_log_filters: list[Any] = []
    having_predicates: list[Any] = []

    # Get order and duration filter
    order = filters.get("order")
    duration_filters = filters.get("duration", [])
    if duration_filters and len(duration_filters) > 0:
        having_predicates.append(asRecordingPropertyFilter(duration_filters[0]))

    # Process each filter
    for f in extracted_filters:
        filter_type = f.get("type")

        if filter_type == "events":
            events.append(f)
        elif filter_type == "actions":
            actions.append(f)
        elif filter_type == "log_entry":
            console_log_filters.append(f)
        elif filter_type == "hogql":
            properties.append(f)
        elif filter_type == "recording":
            if f.get("key") == "visited_page":
                # A recording property filtered over the session's all_urls — matches the frontend
                # converter and the list query, rather than a divergent $pageview/$current_url event.
                properties.append(f)
            elif f.get("key") == "snapshot_source" and f.get("value"):
                having_predicates.append(f)
            else:
                having_predicates.append(asRecordingPropertyFilter(f))
        else:
            # For any other property filter
            properties.append(f)

    try:
        # Construct the RecordingsQuery
        return RecordingsQuery(
            order=order,
            date_from=filters.get("date_from"),
            date_to=filters.get("date_to"),
            properties=properties,
            events=events,
            actions=actions,
            console_log_filters=console_log_filters,
            having_predicates=having_predicates,
            filter_test_accounts=filters.get("filter_test_accounts"),
            operand=_derive_operand(filters.get("filter_group")),
            limit=filters.get("limit"),
        )
    except ValidationError as e:
        # we were seeing errors here and it was hard to debug
        # so we're logging all the data and the error
        logger.exception(
            "Failed to convert universal filters to RecordingsQuery",
            filters=filters,
            error=e,
            having_predicates=having_predicates,
            properties=properties,
            events=events,
            actions=actions,
            console_log_filters=console_log_filters,
            filter_test_accounts=filters.get("filter_test_accounts"),
            operand=_derive_operand(filters.get("filter_group")),
        )
        raise
