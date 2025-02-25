import json

import posthoganalytics
from celery import shared_task
from django.conf import settings
from prometheus_client import Counter, Histogram

from posthog.session_recordings.session_recording_playlist_api import PLAYLIST_COUNT_REDIS_PREFIX
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.session_recording_api import list_recordings_from_query, filter_from_params_to_query
from posthog.tasks.utils import CeleryQueue
from posthog.redis import get_client

from structlog import get_logger

logger = get_logger(__name__)

THIRTY_SIX_HOURS_IN_SECONDS = 36 * 60 * 60

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
)

REPLAY_PLAYLIST_COUNT_TIMER = Histogram(
    "replay_playlist_with_filters_count_timer_seconds",
    "Time spent loading session recordings that match filters in a playlist in seconds",
    buckets=(1, 2, 4, 8, 10, 30, 60, 120, 240, 300, 360, 420, 480, 540, 600, float("inf")),
)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.SESSION_REPLAY_PERSISTENCE.value,
)
def count_recordings_that_match_playlist_filters(playlist_id: int) -> None:
    try:
        with REPLAY_PLAYLIST_COUNT_TIMER.time():
            playlist = SessionRecordingPlaylist.objects.get(id=playlist_id)
            query = filter_from_params_to_query(playlist.filters)
            (recordings, more_recordings_available, _) = list_recordings_from_query(
                query, user=None, team=playlist.team
            )
            redis_client = get_client()
            value_to_set = json.dumps(
                {"session_ids": [r.session_id for r in recordings], "has_more": more_recordings_available}
            )
            redis_client.setex(
                f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}", THIRTY_SIX_HOURS_IN_SECONDS, value_to_set
            )
            REPLAY_TEAM_PLAYLIST_COUNT_SUCCEEDED.inc()
    except Exception as e:
        posthoganalytics.capture_exception(e)
        logger.exception("Failed to count recordings that match playlist filters", playlist_id=playlist_id, error=e)
        REPLAY_TEAM_PLAYLIST_COUNT_FAILED.inc()


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.SESSION_REPLAY_PERSISTENCE.value,
)
def enqueue_recordings_that_match_playlist_filters() -> None:
    teams_with_counter_processing = settings.PLAYLIST_COUNTER_PROCESSING_ALLOWED_TEAMS

    for team in teams_with_counter_processing:
        all_playlists = SessionRecordingPlaylist.objects.filter(team_id=int(team), deleted=False, filters__isnull=False)
        REPLAY_TEAM_PLAYLISTS_IN_TEAM_COUNT.inc(all_playlists.count())

        for playlist in all_playlists:
            count_recordings_that_match_playlist_filters.delay(playlist.id)
