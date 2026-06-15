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


def convert_playlist_to_recordings_query(playlist: SessionRecordingPlaylist) -> RecordingsQuery:
    """Convert playlist with filters to a RecordingsQuery object."""
    filters = playlist.filters

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
            playlist.filters = filters
            playlist.save(update_fields=["filters"])
            REPLAY_PLAYLIST_LEGACY_FILTERS_CONVERTED.inc()

    return convert_filters_to_recordings_query(filters)


def convert_filters_to_recordings_query(filters: dict[str, Any]) -> RecordingsQuery:
    """
    Convert universal filters to a RecordingsQuery object.
    This is the Python equivalent of the frontend's convertUniversalFiltersToRecordingsQuery function.
    """

    # Extract filters from the filter group
    extracted_filters = []
    if filters.get("filter_group") and filters["filter_group"].get("values"):
        # Get the first group (which should be the only one)
        group = filters["filter_group"]["values"][0]
        if group and group.get("values"):
            extracted_filters = group["values"]

    events = []
    actions = []
    properties = []
    console_log_filters = []
    having_predicates = []

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
                events.append(
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "properties": [
                            {
                                "type": "event",
                                "key": "$current_url",
                                "value": f.get("value"),
                                "operator": f.get("operator"),
                            }
                        ],
                    }
                )
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
            operand=filters.get("filter_group", {}).get("type", FilterLogicalOperator.AND_),
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
            operand=filters.get("filter_group", {}).get("type", FilterLogicalOperator.AND_),
        )
        raise
