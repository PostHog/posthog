from datetime import datetime
import json
from typing import Any, Optional
import posthoganalytics
from celery import shared_task
from django.conf import settings
from prometheus_client import Counter, Histogram

from posthog.session_recordings.session_recording_playlist_api import PLAYLIST_COUNT_REDIS_PREFIX
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.session_recording_api import list_recordings_from_query, filter_from_params_to_query
from posthog.tasks.utils import CeleryQueue
from posthog.redis import get_client
from posthog.schema import RecordingsQuery, FilterLogicalOperator, PropertyOperator, PropertyFilterType

from structlog import get_logger

logger = get_logger(__name__)

THIRTY_SIX_HOURS_IN_SECONDS = 36 * 60 * 60
TASK_EXPIRATION_TIME = settings.PLAYLIST_COUNTER_PROCESSING_SCHEDULE_SECONDS or THIRTY_SIX_HOURS_IN_SECONDS

REPLAY_TEAM_PLAYLISTS_IN_TEAM_COUNT = Counter(
    "replay_playlist_with_filters_in_team_count",
    "Count of session recording playlists with filters in a team",
)

REPLAY_TEAM_PLAYLIST_COUNT_SUCCEEDED = Counter(
    "replay_playlist_count_succeeded",
    "when a count task for a playlist succeeds",
)

REPLAY_TEAM_PLAYLIST_COUNT_FAILED = Counter(
    "replay_playlist_count_failed",
    "when a count task for a playlist fails",
    labelnames=["error"],
)

REPLAY_TEAM_PLAYLIST_COUNT_UNKNOWN = Counter(
    "replay_playlist_count_unknown",
    "when a count task for a playlist is unknown",
)

REPLAY_TEAM_PLAYLIST_COUNT_SKIPPED = Counter(
    "replay_playlist_count_skipped",
    "when a count task for a playlist is skipped because the cooldown period has not passed",
)

REPLAY_PLAYLIST_LEGACY_FILTERS_CONVERTED = Counter(
    "replay_playlist_legacy_filters_converted",
    "when a count task for a playlist converts legacy filters to universal filters",
)


REPLAY_PLAYLIST_COUNT_TIMER = Histogram(
    "replay_playlist_with_filters_count_timer_seconds",
    "Time spent loading session recordings that match filters in a playlist in seconds",
    buckets=(1, 2, 4, 8, 10, 30, 60, 120, 240, 300, 360, 420, 480, 540, 600, float("inf")),
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


def convert_filters_to_recordings_query(playlist: SessionRecordingPlaylist) -> RecordingsQuery:
    """
    Convert universal filters to a RecordingsQuery object.
    This is the Python equivalent of the frontend's convertUniversalFiltersToRecordingsQuery function.
    """

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

    # Extract filters from the filter group
    extracted_filters = []
    if filters.get("filter_group") and filters["filter_group"].get("values"):
        # Get the first group (which should be the only one)
        group = filters["filter_group"]["values"][0]
        if group and group.get("values"):
            extracted_filters = group["values"]
    else:
        raise Exception("Invalid universal filters")

    events = []
    actions = []
    properties = []
    console_log_filters = []
    having_predicates = []

    # Get order and duration filter
    order = filters.get("order")
    duration_filters = filters.get("duration", [])
    if duration_filters and len(duration_filters) > 0:
        having_predicates.append(duration_filters[0])

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
                properties.append(f)
        else:
            # For any other property filter
            properties.append(f)

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
    )


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.SESSION_REPLAY_GENERAL.value,
    # limit how many run per worker instance - if we have 10 workers, this will run 600 times per hour
    rate_limit="60/h",
    expires=TASK_EXPIRATION_TIME,
)
def count_recordings_that_match_playlist_filters(playlist_id: int) -> None:
    playlist: SessionRecordingPlaylist | None = None
    query: RecordingsQuery | None = None
    try:
        with REPLAY_PLAYLIST_COUNT_TIMER.time():
            playlist = SessionRecordingPlaylist.objects.get(id=playlist_id)
            redis_client = get_client()

            existing_value = redis_client.get(f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}")
            if existing_value:
                existing_value = json.loads(existing_value)
            else:
                existing_value = {}

            # if we have results from the last hour we don't need to run the query
            if existing_value.get("refreshed_at"):
                last_refreshed_at = datetime.fromisoformat(existing_value["refreshed_at"])
                seconds_since_refresh = int((datetime.now() - last_refreshed_at).total_seconds())

                if seconds_since_refresh <= settings.PLAYLIST_COUNTER_PROCESSING_COOLDOWN_SECONDS:
                    REPLAY_TEAM_PLAYLIST_COUNT_SKIPPED.inc()
                    return

            query = convert_filters_to_recordings_query(playlist)
            (recordings, more_recordings_available, _) = list_recordings_from_query(
                query, user=None, team=playlist.team
            )

            value_to_set = json.dumps(
                {
                    "session_ids": [r.session_id for r in recordings],
                    "has_more": more_recordings_available,
                    "previous_ids": existing_value.get("session_ids", None),
                    "refreshed_at": datetime.now().isoformat(),
                }
            )
            redis_client.setex(
                f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}", THIRTY_SIX_HOURS_IN_SECONDS, value_to_set
            )

            REPLAY_TEAM_PLAYLIST_COUNT_SUCCEEDED.inc()
    except SessionRecordingPlaylist.DoesNotExist:
        logger.info(
            "Playlist does not exist",
            playlist_id=playlist_id,
            playlist_short_id=playlist.short_id if playlist else None,
        )
        REPLAY_TEAM_PLAYLIST_COUNT_UNKNOWN.inc()
    except Exception as e:
        posthoganalytics.capture_exception(
            e,
            properties={
                "playlist_id": playlist_id,
                "playlist_short_id": playlist.short_id if playlist else None,
                "posthog_feature": "session_replay_playlist_counters",
                "filters": playlist.filters if playlist else None,
                "query": query.model_dump_json() if query else None,
            },
        )
        logger.exception(
            "Failed to count recordings that match playlist filters",
            playlist_id=playlist_id,
            playlist_short_id=playlist.short_id if playlist else None,
            filters=playlist.filters if playlist else None,
            query=query.model_dump_json() if query else None,
            error=e,
        )
        REPLAY_TEAM_PLAYLIST_COUNT_FAILED.labels(error=e.__class__.__name__).inc()


def enqueue_recordings_that_match_playlist_filters() -> None:
    if not settings.PLAYLIST_COUNTER_PROCESSING_MAX_ALLOWED_TEAM_ID or not isinstance(
        settings.PLAYLIST_COUNTER_PROCESSING_MAX_ALLOWED_TEAM_ID, int
    ):
        raise Exception("PLAYLIST_COUNTER_PROCESSING_MAX_ALLOWED_TEAM_ID is not set")

    if settings.PLAYLIST_COUNTER_PROCESSING_MAX_ALLOWED_TEAM_ID == 0:
        # If we're not processing any teams, we don't need to enqueue anything
        return

    all_playlists = SessionRecordingPlaylist.objects.filter(
        team_id__lte=int(settings.PLAYLIST_COUNTER_PROCESSING_MAX_ALLOWED_TEAM_ID), deleted=False, filters__isnull=False
    )
    REPLAY_TEAM_PLAYLISTS_IN_TEAM_COUNT.inc(all_playlists.count())

    for playlist in all_playlists:
        count_recordings_that_match_playlist_filters.delay(playlist.id)
