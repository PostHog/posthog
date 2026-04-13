import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.session_replay.count_playlist_items.types import CountPlaylistInput, PlaylistInfo
from posthog.temporal.session_replay.count_playlist_items.workflows import (
    CountAllPlaylistsWorkflow,
    CountPlaylistWorkflow,
)


@pytest.mark.asyncio
async def test_fans_out_child_workflows():
    playlists = [PlaylistInfo(playlist_id=1), PlaylistInfo(playlist_id=2), PlaylistInfo(playlist_id=3)]
    counted_ids: list[int] = []

    @activity.defn(name="fetch-playlists-to-count")
    async def mock_fetch() -> list[PlaylistInfo]:
        return playlists

    @activity.defn(name="count-recordings-for-playlist")
    async def mock_count(input: CountPlaylistInput) -> None:
        counted_ids.append(input.playlist_id)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[CountAllPlaylistsWorkflow, CountPlaylistWorkflow],
            activities=[mock_fetch, mock_count],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                CountAllPlaylistsWorkflow.run,
                None,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert sorted(counted_ids) == [1, 2, 3]


@pytest.mark.asyncio
async def test_no_playlists_completes_immediately():
    @activity.defn(name="fetch-playlists-to-count")
    async def mock_fetch() -> list[PlaylistInfo]:
        return []

    @activity.defn(name="count-recordings-for-playlist")
    async def mock_count(input: CountPlaylistInput) -> None:
        raise AssertionError("should not be called")

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[CountAllPlaylistsWorkflow, CountPlaylistWorkflow],
            activities=[mock_fetch, mock_count],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                CountAllPlaylistsWorkflow.run,
                None,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )


@pytest.mark.asyncio
async def test_partial_failure_raises_application_error():
    playlists = [PlaylistInfo(playlist_id=1), PlaylistInfo(playlist_id=2)]

    @activity.defn(name="fetch-playlists-to-count")
    async def mock_fetch() -> list[PlaylistInfo]:
        return playlists

    @activity.defn(name="count-recordings-for-playlist")
    async def mock_count(input: CountPlaylistInput) -> None:
        if input.playlist_id == 2:
            raise RuntimeError("ClickHouse timeout")

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[CountAllPlaylistsWorkflow, CountPlaylistWorkflow],
            activities=[mock_fetch, mock_count],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError) as exc_info:
                await env.client.execute_workflow(
                    CountAllPlaylistsWorkflow.run,
                    None,
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )
            assert isinstance(exc_info.value.cause, ApplicationError)
            assert "Playlist counting failed" in str(exc_info.value.cause)


@pytest.mark.asyncio
async def test_count_playlist_workflow_calls_activity():
    counted_ids: list[int] = []

    @activity.defn(name="count-recordings-for-playlist")
    async def mock_count(input: CountPlaylistInput) -> None:
        counted_ids.append(input.playlist_id)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[CountPlaylistWorkflow],
            activities=[mock_count],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                CountPlaylistWorkflow.run,
                CountPlaylistInput(playlist_id=42),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert counted_ids == [42]
