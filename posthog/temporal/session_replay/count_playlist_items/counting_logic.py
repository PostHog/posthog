import json
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db.models import Count, F, Q
from django.utils import timezone

import posthoganalytics
from prometheus_client import Counter, Gauge, Histogram
from structlog import get_logger

from posthog.schema import RecordingsQuery

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.helpers.session_recording_playlist_templates import DEFAULT_PLAYLIST_NAMES
from posthog.redis import get_client
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.playlist_filters import DEFAULT_RECORDING_FILTERS, convert_playlist_to_recordings_query
from posthog.session_recordings.session_recording_api import list_recordings_from_query
from posthog.session_recordings.session_recording_playlist_api import PLAYLIST_COUNT_REDIS_PREFIX

logger = get_logger(__name__)

THIRTY_SIX_HOURS_IN_SECONDS = 36 * 60 * 60
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
    labelnames=["reason"],
)

REPLAY_PLAYLIST_COULD_NOT_ADD_ERROR_COUNT = Counter(
    "replay_playlist_could_not_add_error_count",
    "when a count task for a playlist could not add an error count",
)


REPLAY_PLAYLIST_COUNT_TIMER = Histogram(
    "replay_playlist_with_filters_count_timer_seconds",
    "Time spent loading session recordings that match filters in a playlist in seconds",
    buckets=(1, 2, 4, 8, 10, 30, 60, 120, 240, 300, 360, 420, 480, 540, 600, float("inf")),
)

REPLAY_TOTAL_PLAYLISTS_GAUGE = Gauge(
    "replay_total_playlists_gauge",
    "Total number of playlists in the database",
)

REPLAY_PLAYLISTS_IN_REDIS_GAUGE = Gauge(
    "replay_playlists_in_redis_gauge",
    "Number of playlists in Redis",
)


def count_playlists_in_redis() -> int:
    redis_client = get_client()
    playlist_count = 0
    cursor = 0
    while True:
        cursor, keys = redis_client.scan(cursor, match=f"{PLAYLIST_COUNT_REDIS_PREFIX}*", count=1000)
        playlist_count += len(keys)
        if cursor == 0:
            break
    return playlist_count


def try_to_store_error_count(playlist_short_id: str | None) -> None:
    try:
        if not playlist_short_id:
            return

        redis_client = get_client()

        existing_value = redis_client.get(f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist_short_id}")
        if existing_value:
            existing_value = json.loads(existing_value)
        else:
            existing_value = {}

        error_date = timezone.now()
        value_to_set = json.dumps(
            {
                **existing_value,
                "errored_at": error_date.isoformat(),
                "error_count": existing_value.get("error_count", 0) + 1,
            }
        )

        redis_client.setex(
            f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist_short_id}", THIRTY_SIX_HOURS_IN_SECONDS, value_to_set
        )
    except Exception:
        REPLAY_PLAYLIST_COULD_NOT_ADD_ERROR_COUNT.inc()
        pass


def safe_seconds_difference(dt1: datetime, dt2: datetime) -> int:
    """
    Returns the difference in seconds between two datetime objects,
    making sure they are timezone-aware. or python will complain
    """
    if dt1.tzinfo is None:
        dt1 = timezone.make_aware(dt1)
    if dt2.tzinfo is None:
        dt2 = timezone.make_aware(dt2)
    return int((dt1 - dt2).total_seconds())


def should_skip_task(existing_value: dict[str, Any], playlist_filters: dict[str, Any]) -> bool:
    # if we have results from the last hour we don't need to run the query
    if existing_value.get("refreshed_at"):
        last_refreshed_at = datetime.fromisoformat(existing_value["refreshed_at"])
        # Make last_refreshed_at timezone-aware if it isn't already
        seconds_since_refresh = safe_seconds_difference(timezone.now(), last_refreshed_at)

        if seconds_since_refresh <= settings.PLAYLIST_COUNTER_PROCESSING_COOLDOWN_SECONDS:
            REPLAY_TEAM_PLAYLIST_COUNT_SKIPPED.labels(reason="cooldown").inc()
            return True

    # don't retry for a while if we're getting errors
    if existing_value.get("errored_at"):
        last_errored_at = datetime.fromisoformat(existing_value["errored_at"])
        seconds_since_refresh = safe_seconds_difference(timezone.now(), last_errored_at)

        if seconds_since_refresh <= settings.PLAYLIST_COUNTER_PROCESSING_COOLDOWN_SECONDS:
            REPLAY_TEAM_PLAYLIST_COUNT_SKIPPED.labels(reason="error_cooldown").inc()
            return True

    # don't keep retrying if we keep getting errors
    if existing_value.get("error_count", 0) >= 5:
        REPLAY_TEAM_PLAYLIST_COUNT_SKIPPED.labels(reason="max_error_cooldown").inc()
        return True

    # if this is the default filters, then we shouldn't have allowed this to be created - we can skip it
    if playlist_filters == DEFAULT_RECORDING_FILTERS:
        REPLAY_TEAM_PLAYLIST_COUNT_SKIPPED.labels(reason="default_filters").inc()
        return True

    return False


def parse_expiry(expiry: str | None) -> datetime | None:
    if expiry is None:
        return None
    try:
        parsed = datetime.fromisoformat(expiry)
        if parsed.tzinfo is None:
            parsed = timezone.make_aware(parsed)
        return parsed
    except (ValueError, TypeError):
        return None


def is_session_unexpired(expiry: str | None, now: datetime) -> bool:
    if expiry is None:
        return True
    parsed = parse_expiry(expiry)
    if parsed is None:
        return False
    return parsed >= now


def count_recordings_that_match_playlist_filters(playlist_id: int) -> None:
    """Core sync counting logic for a single playlist.

    Used by the Temporal activity and tests.
    """
    playlist: SessionRecordingPlaylist | None = None
    query: RecordingsQuery | None = None
    try:
        with REPLAY_PLAYLIST_COUNT_TIMER.time():
            # nosemgrep: idor-lookup-without-team (Internal scheduling, not user input)
            playlist = SessionRecordingPlaylist.objects.get(id=playlist_id)
            redis_client = get_client()

            tag_queries(
                product=Product.REPLAY, feature=Feature.QUERY, team_id=playlist.team.pk, replay_playlist_id=playlist_id
            )

            existing_value = redis_client.getex(
                name=f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}", ex=THIRTY_SIX_HOURS_IN_SECONDS
            )
            if existing_value:
                existing_value = json.loads(existing_value)
            else:
                existing_value = {}

            if should_skip_task(existing_value, playlist.filters):
                return

            query = convert_playlist_to_recordings_query(playlist)

            should_query_incrementally = (
                existing_value.get("refreshed_at", None)
                and query.order == "start_time"
                and existing_value.get("version") == 2
            )

            if should_query_incrementally:
                query.date_from = existing_value["refreshed_at"]

            (recordings, more_recordings_available, _, _) = list_recordings_from_query(
                query, user=None, team=playlist.team
            )

            counted_at_date = timezone.now()
            new_sessions: dict[str, str | None] = {
                r.session_id: r.expiry_time.isoformat() if r.expiry_time else None for r in recordings
            }

            if should_query_incrementally:
                existing_sessions = existing_value.get("sessions_with_expiry", {})
                for sid, expiry in existing_sessions.items():
                    if sid in new_sessions:
                        continue
                    if is_session_unexpired(expiry, counted_at_date):
                        new_sessions[sid] = expiry

            value_to_set = json.dumps(
                {
                    "version": 2,
                    "session_ids": list(new_sessions.keys()),
                    "sessions_with_expiry": new_sessions,
                    "has_more": more_recordings_available,
                    "previous_ids": existing_value.get("session_ids", None),
                    "refreshed_at": counted_at_date.isoformat(),
                    "error_count": 0,
                    "errored_at": None,
                }
            )
            redis_client.setex(
                f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}", THIRTY_SIX_HOURS_IN_SECONDS, value_to_set
            )
            playlist.last_counted_at = counted_at_date
            playlist.save(update_fields=["last_counted_at"])

            REPLAY_TEAM_PLAYLIST_COUNT_SUCCEEDED.inc()
            posthoganalytics.capture(
                distinct_id=f"playlist_counting_for_team_{playlist.team.pk}",
                event="replay_playlist_saved_filters_counted",
                properties={
                    "team_id": playlist.team.pk,
                    "saved_filters_short_id": playlist.short_id,
                    "saved_filters_name": playlist.name or playlist.derived_name,
                    "count": len(new_sessions),
                    "previous_count": len(existing_value.get("session_ids", [])),
                },
            )
    except SessionRecordingPlaylist.DoesNotExist:
        logger.info(
            "Playlist does not exist",
            playlist_id=playlist_id,
            playlist_short_id=playlist.short_id if playlist else None,
        )
        REPLAY_TEAM_PLAYLIST_COUNT_UNKNOWN.inc()
    except Exception as e:
        query_json: dict[str, Any] | None = None
        try:
            query_json = query.model_dump() if query else None
        except Exception:
            query_json = {"malformed": True}

        posthoganalytics.capture_exception(
            e,
            properties={
                "playlist_id": playlist_id,
                "playlist_short_id": playlist.short_id if playlist else None,
                "posthog_feature": "session_replay_playlist_counters",
            },
        )
        logger.exception(
            "Failed to count recordings that match playlist filters",
            playlist_id=playlist_id,
            playlist_short_id=playlist.short_id if playlist else None,
            query=query_json,
            error=e,
        )
        REPLAY_TEAM_PLAYLIST_COUNT_FAILED.labels(error=e.__class__.__name__).inc()
        try_to_store_error_count(playlist.short_id if playlist else None)


def fetch_playlists_to_count() -> list[int]:
    """Fetch playlist IDs that need counting. Used by the Temporal activity and tests."""
    base_query = (
        SessionRecordingPlaylist.objects.filter(
            deleted=False,
            filters__isnull=False,
        )
        .filter(Q(last_counted_at__isnull=True) | Q(last_counted_at__lt=timezone.now() - timedelta(hours=2)))
        .exclude(name__in=DEFAULT_PLAYLIST_NAMES)
        .annotate(pinned_item_count=Count("playlist_items"))
        .filter(pinned_item_count=0)
    )

    total_playlists_count = base_query.count()

    all_playlist_ids = list(
        base_query.order_by(F("last_counted_at").asc(nulls_first=True)).values_list("id", flat=True)[
            : settings.PLAYLIST_COUNTER_PROCESSING_PLAYLISTS_LIMIT
        ]
    )

    cached_counted_playlists_count = count_playlists_in_redis()

    REPLAY_TOTAL_PLAYLISTS_GAUGE.set(total_playlists_count)
    REPLAY_PLAYLISTS_IN_REDIS_GAUGE.set(cached_counted_playlists_count)

    return all_playlist_ids
