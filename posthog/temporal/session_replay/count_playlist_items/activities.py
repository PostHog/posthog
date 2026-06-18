from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.session_replay.count_playlist_items.counting_logic import (
    count_recordings_that_match_playlist_filters,
    fetch_playlists_to_count as fetch_playlists_to_count_sync,
)
from posthog.temporal.session_replay.count_playlist_items.types import CountPlaylistInput, PlaylistInfo

LOGGER = get_write_only_logger()


@activity.defn(name="fetch-playlists-to-count")
async def fetch_playlists_to_count() -> list[PlaylistInfo]:
    logger = LOGGER.bind(activity="fetch-playlists-to-count")
    logger.info("Fetching playlists to count")

    playlist_ids = await database_sync_to_async(fetch_playlists_to_count_sync)()

    logger.info("Found playlists to count", to_count=len(playlist_ids))

    return [PlaylistInfo(playlist_id=pid) for pid in playlist_ids]


@activity.defn(name="count-recordings-for-playlist")
async def count_recordings_for_playlist(input: CountPlaylistInput) -> None:
    logger = LOGGER.bind(activity="count-recordings-for-playlist", playlist_id=input.playlist_id)
    logger.info("Counting recordings for playlist")
    async with Heartbeater():
        await database_sync_to_async(count_recordings_that_match_playlist_filters)(input.playlist_id)
    logger.info("Finished counting recordings for playlist")
