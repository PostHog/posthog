from posthog.temporal.session_replay.count_playlist_items.activities import (
    count_recordings_for_playlist,
    fetch_playlists_to_count,
)
from posthog.temporal.session_replay.count_playlist_items.counting_logic import (
    convert_filters_to_recordings_query,
    convert_playlist_to_recordings_query,
)
from posthog.temporal.session_replay.count_playlist_items.workflow import (
    CountAllPlaylistsWorkflow,
    CountPlaylistWorkflow,
)

COUNT_PLAYLIST_ITEMS_WORKFLOWS = [
    CountAllPlaylistsWorkflow,
    CountPlaylistWorkflow,
]

COUNT_PLAYLIST_ITEMS_ACTIVITIES = [
    fetch_playlists_to_count,
    count_recordings_for_playlist,
]

__all__ = [
    "COUNT_PLAYLIST_ITEMS_ACTIVITIES",
    "COUNT_PLAYLIST_ITEMS_WORKFLOWS",
    "convert_filters_to_recordings_query",
    "convert_playlist_to_recordings_query",
]
