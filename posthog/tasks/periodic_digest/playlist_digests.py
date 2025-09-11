import json
import dataclasses
from datetime import datetime, timedelta
from typing import Literal

from django.db.models import Count, Q, QuerySet
from django.db.models.functions import Now

from posthog.helpers.session_recording_playlist_templates import DEFAULT_PLAYLIST_NAMES
from posthog.redis import get_client
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist

# soon playlists will have a type, and we can explicitly count saved_filters and collections separately,
# but for now saved_filters are playlists without pinned items - they are counted in redis
# collections are playlists with pinned items - they are counted in postgres


@dataclasses.dataclass
class CountedPlaylist:
    team_id: int
    name: str
    short_id: str
    derived_name: str | None
    # number of session recordings in the playlist
    # for a collection this is the total
    # for a saved filter this is the count of at most the first page
    count: int | None
    has_more_available: bool
    type: Literal["collection", "filters"]
    # the number of times this was viewed
    view_count: int | None = None
    # the number of users that viewed this
    user_count: int | None = None

    @property
    def url_path(self) -> str | None:
        """
        playlists are split into two types and have different URL paths depending on the type
        """
        match self.type:
            case "collection":
                return f"/replay/playlists/{self.short_id}"
            case "filters":
                return f"/replay/home/?filterId={self.short_id}"
            case _:
                raise ValueError(f"Unexpected playlist type: {self.type}")


def _prepare_counted_playlists(qs: QuerySet) -> list[CountedPlaylist]:
    playlist_count_redis_prefix: str | None = None
    try:
        from ee.session_recordings.playlist_counters.recordings_that_match_playlist_filters import (
            PLAYLIST_COUNT_REDIS_PREFIX,
        )

        # use this key as the probe to check if EE features (and so playlist counting) are available
        playlist_count_redis_prefix = PLAYLIST_COUNT_REDIS_PREFIX
    except ImportError:
        pass

    results = []

    playlists = list(qs)

    # For each playlist,
    # we want a list of cached counts (if there is one)
    # or None (if there is not).
    # So that the list of cached counts is the same length as the list of playlists.
    # And we can zip them together
    # to only loop over the playlists once
    cached_playlist_counts = []
    if playlist_count_redis_prefix:
        redis = get_client()
        keys = [f"{playlist_count_redis_prefix}{p['short_id']}" for p in playlists]
        cached_playlist_counts = redis.mget(keys)
    else:
        cached_playlist_counts = [None] * len(playlists)

    for playlist, count in zip(playlists, cached_playlist_counts):
        playlist_count = None
        has_more = False

        # Use pinned_item_count if > 0, else try redis
        if playlist.get("pinned_item_count", 0) > 0:
            playlist_count = playlist["pinned_item_count"]
            has_more = False
        # Use the cached count from redis if available
        elif count is not None:
            try:
                data = json.loads(count)
                playlist_count = len(data.get("session_ids", []))
                has_more = data.get("has_more", False)
            except Exception:
                pass

        playlist_type: Literal["collection", "filters"] | None = playlist.get("type")
        if playlist_type is None:
            playlist_type = "collection" if playlist.get("pinned_item_count", 0) > 0 else "filters"

        results.append(
            CountedPlaylist(
                team_id=playlist["team_id"],
                name=playlist["name"],
                short_id=playlist["short_id"],
                derived_name=playlist["derived_name"],
                count=playlist_count,
                has_more_available=has_more,
                view_count=playlist["view_count"],
                user_count=playlist["user_count"],
                type=playlist_type,
            )
        )

    results.sort(
        key=lambda p: (
            p.count is None,  # First sort by whether count exists
            p.view_count is None,  # Then by whether view_count exists
            p.user_count is None,  # Then by whether user_count exists
            -(p.user_count or 0),  # Then by user_count (descending)
            -(p.view_count or 0),  # Then by view_count (descending)
            -(p.count or 0),  # Finally, by count (descending)
        )
    )

    return results


def get_teams_with_interesting_playlists(end: datetime) -> list[CountedPlaylist]:
    qs = (
        SessionRecordingPlaylist.objects.exclude(deleted=True)
        .exclude(name__in=DEFAULT_PLAYLIST_NAMES)
        .exclude(
            (Q(name__isnull=True) | Q(name="Unnamed") | Q(name=""))
            & (
                Q(derived_name__isnull=True)
                | Q(derived_name="(Untitled)")
                | Q(derived_name="Unnamed")
                | Q(derived_name="")
            )
        )
        .annotate(
            pinned_item_count=Count("playlist_items"),
            # count views in the last 4 weeks
            view_count=Count(
                "sessionrecordingplaylistviewed",
                filter=Q(sessionrecordingplaylistviewed__viewed_at__gte=end - timedelta(weeks=4)),
            ),
            # count users viewing in the last 4 weeks
            user_count=Count(
                "sessionrecordingplaylistviewed__user_id",
                filter=Q(sessionrecordingplaylistviewed__viewed_at__gte=end - timedelta(weeks=4)),
                distinct=True,
            ),
        )
        .values("team_id", "name", "short_id", "derived_name", "pinned_item_count", "view_count", "user_count", "type")
    )

    return _prepare_counted_playlists(qs)


def get_teams_with_new_playlists(end: datetime, begin: datetime) -> list[CountedPlaylist]:
    qs = (
        SessionRecordingPlaylist.objects.filter(
            created_at__gt=begin,
            created_at__lte=end,
        )
        .exclude(
            (Q(name__isnull=True) | Q(name="Unnamed") | Q(name=""))
            & (
                Q(derived_name__isnull=True)
                | Q(derived_name="(Untitled)")
                | Q(derived_name="Unnamed")
                | Q(derived_name="")
            )
        )
        .exclude(deleted=True)
        .exclude(name__in=DEFAULT_PLAYLIST_NAMES)
        .annotate(
            pinned_item_count=Count("playlist_items"),
            view_count=Count(
                "sessionrecordingplaylistviewed",
                filter=Q(sessionrecordingplaylistviewed__viewed_at__gte=Now() - timedelta(weeks=4)),
            ),
            user_count=Count(
                "sessionrecordingplaylistviewed__user_id",
                filter=Q(sessionrecordingplaylistviewed__viewed_at__gte=Now() - timedelta(weeks=4)),
                distinct=True,
            ),
        )
        .values("team_id", "name", "short_id", "derived_name", "pinned_item_count", "view_count", "user_count", "type")
    )

    return _prepare_counted_playlists(qs)
