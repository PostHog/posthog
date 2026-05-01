import json
import asyncio
from datetime import timedelta

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.session_replay.count_playlist_items.activities import (
    count_recordings_for_playlist,
    fetch_playlists_to_count,
)
from posthog.temporal.session_replay.count_playlist_items.types import CountPlaylistInput, PlaylistInfo


@temporalio.workflow.defn(name="count-all-playlists")
class CountAllPlaylistsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @temporalio.workflow.run
    async def run(self, input: None = None) -> None:
        playlist_infos: list[PlaylistInfo] = await temporalio.workflow.execute_activity(
            fetch_playlists_to_count,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=timedelta(seconds=10),
                maximum_interval=timedelta(minutes=2),
                maximum_attempts=3,
            ),
        )

        if not playlist_infos:
            return

        BATCH_SIZE = 500
        failed_ids = []

        for batch_start in range(0, len(playlist_infos), BATCH_SIZE):
            batch = playlist_infos[batch_start : batch_start + BATCH_SIZE]

            tasks = []
            for info in batch:
                task = temporalio.workflow.execute_child_workflow(
                    CountPlaylistWorkflow.run,
                    CountPlaylistInput(playlist_id=info.playlist_id),
                    id=f"count-playlist-{info.playlist_id}",
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                    execution_timeout=timedelta(minutes=30),
                )
                tasks.append((info.playlist_id, task))

            results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)

            for (playlist_id, _), result in zip(tasks, results):
                if isinstance(result, BaseException):
                    if isinstance(result, WorkflowAlreadyStartedError):
                        temporalio.workflow.logger.info(
                            "count_playlist.already_running",
                            extra={"playlist_id": playlist_id},
                        )
                    else:
                        failed_ids.append(playlist_id)
                        temporalio.workflow.logger.warning(
                            "count_playlist.child_workflow_error",
                            extra={"playlist_id": playlist_id, "error": str(result)},
                        )

        if failed_ids:
            raise ApplicationError(
                f"Playlist counting failed for {len(failed_ids)}/{len(playlist_infos)} playlists",
            )


@temporalio.workflow.defn(name="count-playlist")
class CountPlaylistWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> CountPlaylistInput:
        loaded = json.loads(inputs[0])
        return CountPlaylistInput(**loaded)

    @temporalio.workflow.run
    async def run(self, input: CountPlaylistInput) -> None:
        await temporalio.workflow.execute_activity(
            count_recordings_for_playlist,
            input,
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=2),
            ),
        )
