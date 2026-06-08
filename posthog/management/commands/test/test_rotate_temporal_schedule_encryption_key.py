import csv
import uuid
import asyncio
import datetime as dt
from io import StringIO

import pytest

from django.core.management import call_command

from cryptography.fernet import InvalidToken
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleDescription,
    ScheduleIntervalSpec,
    ScheduleListActionStartWorkflow,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.service import RPCError

from posthog.temporal.common.client import async_connect, connect

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

OLD_TEMPORAL_SECRET_KEY = "old-key-for-schedule-rotation-test"
NEW_TEMPORAL_SECRET_KEY = "new-key-for-schedule-rotation-test"


@pytest.fixture
async def temporal() -> Client:
    return await async_connect()


@pytest.fixture
async def schedule_ids(temporal: Client):
    created_schedule_ids: list[str] = []
    yield created_schedule_ids

    for schedule_id in created_schedule_ids:
        await _delete_schedule(temporal, schedule_id)


def _schedule_id() -> str:
    return f"test-rotate-temporal-schedule-key-{uuid.uuid4()}"


def _workflow_name() -> str:
    return f"test-rotate-temporal-schedule-key-workflow-{uuid.uuid4()}"


async def _connect_with_keys(settings, secret_key: str, fallback_keys: list[str] | None = None) -> Client:
    settings.TEMPORAL_SECRET_KEY = secret_key
    settings.TEMPORAL_FALLBACK_SECRET_KEYS = fallback_keys or []
    return await async_connect()


async def _connect_without_encryption(settings) -> Client:
    return await connect(
        settings.TEMPORAL_HOST,
        settings.TEMPORAL_PORT,
        settings.TEMPORAL_NAMESPACE,
        settings.TEMPORAL_CLIENT_CERT,
        settings.TEMPORAL_CLIENT_KEY,
        settings=None,
    )


async def _create_schedule(
    temporal: Client, schedule_id: str, workflow_name: str, *, note: str = "existing note"
) -> None:
    await temporal.create_schedule(
        schedule_id,
        Schedule(
            action=ScheduleActionStartWorkflow(
                workflow_name,
                args=[{"schedule_id": schedule_id}],
                id=f"{schedule_id}-workflow",
                task_queue="test-task-queue",
            ),
            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=dt.timedelta(days=365))]),
            state=ScheduleState(note=note, paused=True),
        ),
    )


async def _delete_schedule(temporal: Client, schedule_id: str) -> None:
    try:
        await temporal.get_schedule_handle(schedule_id).delete()
    except RPCError:
        pass


async def _describe_schedule(temporal: Client, schedule_id: str) -> ScheduleDescription:
    return await temporal.get_schedule_handle(schedule_id).describe()


async def _decode_schedule_args(temporal: Client, schedule_id: str) -> list[object]:
    description = await temporal.get_schedule_handle(schedule_id).describe()
    action = description.schedule.action
    assert isinstance(action, ScheduleActionStartWorkflow)
    return await temporal.data_converter.decode(list(action.args))


async def _list_schedule_ids_for_workflow(temporal: Client, workflow_name: str) -> list[str]:
    schedule_ids: list[str] = []
    async for listing in await temporal.list_schedules():
        action = listing.schedule.action if listing.schedule else None
        if isinstance(action, ScheduleListActionStartWorkflow) and action.workflow == workflow_name:
            schedule_ids.append(listing.id)
    return schedule_ids


async def _wait_for_schedule_listed_by_workflow(temporal: Client, schedule_id: str, workflow_name: str) -> None:
    deadline = asyncio.get_running_loop().time() + 10
    while asyncio.get_running_loop().time() < deadline:
        if schedule_id in await _list_schedule_ids_for_workflow(temporal, workflow_name):
            return
        await asyncio.sleep(0.5)

    raise AssertionError(f"Schedule {schedule_id} was not listed for workflow {workflow_name}")


async def _call_command(*args: str) -> None:
    await asyncio.to_thread(call_command, "rotate_temporal_schedule_encryption_key", *args)


def _csv_output(output: str) -> list[list[str]]:
    return list(csv.reader(StringIO(output)))


async def test_rotate_by_id_updates_schedule_key_and_writes_csv(
    settings, schedule_ids: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    schedule_id = _schedule_id()
    schedule_ids.append(schedule_id)
    old_key_client = await _connect_with_keys(settings, OLD_TEMPORAL_SECRET_KEY)
    await _create_schedule(old_key_client, schedule_id, _workflow_name())

    new_key_client = await _connect_with_keys(settings, NEW_TEMPORAL_SECRET_KEY)
    with pytest.raises(InvalidToken):
        await _decode_schedule_args(new_key_client, schedule_id)

    await _connect_with_keys(settings, NEW_TEMPORAL_SECRET_KEY, [OLD_TEMPORAL_SECRET_KEY])

    await _call_command(
        "--format=csv",
        "id",
        schedule_id,
    )

    captured = capsys.readouterr()
    assert _csv_output(captured.out) == [
        ["schedule_id", "status", "details"],
        [schedule_id, "success", ""],
    ]

    new_key_client = await _connect_with_keys(settings, NEW_TEMPORAL_SECRET_KEY)
    description = await _describe_schedule(new_key_client, schedule_id)
    assert description.schedule.state.note is not None
    assert "Schedule inputs re-encrypted on" in description.schedule.state.note
    assert "existing note" in description.schedule.state.note
    assert await _decode_schedule_args(new_key_client, schedule_id) == [{"schedule_id": schedule_id}]


async def test_rotate_by_id_skips_schedule_already_using_main_key(
    settings, schedule_ids: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    schedule_id = _schedule_id()
    schedule_ids.append(schedule_id)
    new_key_client = await _connect_with_keys(settings, NEW_TEMPORAL_SECRET_KEY)
    await _create_schedule(new_key_client, schedule_id, _workflow_name())

    await _connect_with_keys(settings, NEW_TEMPORAL_SECRET_KEY, [OLD_TEMPORAL_SECRET_KEY])

    await _call_command(
        "--format=csv",
        "id",
        schedule_id,
    )

    captured = capsys.readouterr()
    assert _csv_output(captured.out) == [
        ["schedule_id", "status", "details"],
        [schedule_id, "skipped", "Main encryption key already in use"],
    ]

    description = await _describe_schedule(new_key_client, schedule_id)
    assert description.schedule.state.note == "existing note"
    assert await _decode_schedule_args(new_key_client, schedule_id) == [{"schedule_id": schedule_id}]


async def test_rotate_by_id_skips_schedule_without_encrypted_args(
    settings, schedule_ids: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    schedule_id = _schedule_id()
    schedule_ids.append(schedule_id)
    unencrypted_client = await _connect_without_encryption(settings)
    await _create_schedule(unencrypted_client, schedule_id, _workflow_name())

    await _connect_with_keys(settings, NEW_TEMPORAL_SECRET_KEY, [OLD_TEMPORAL_SECRET_KEY])

    await _call_command(
        "--format=csv",
        "id",
        schedule_id,
    )

    captured = capsys.readouterr()
    assert _csv_output(captured.out) == [
        ["schedule_id", "status", "details"],
        [schedule_id, "skipped", "No encryption in use"],
    ]

    description = await _describe_schedule(unencrypted_client, schedule_id)
    assert description.schedule.state.note == "existing note"
    assert await _decode_schedule_args(unencrypted_client, schedule_id) == [{"schedule_id": schedule_id}]


async def test_dry_run_does_not_update_schedule(
    settings, schedule_ids: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    schedule_id = _schedule_id()
    schedule_ids.append(schedule_id)
    old_key_client = await _connect_with_keys(settings, OLD_TEMPORAL_SECRET_KEY)
    await _create_schedule(old_key_client, schedule_id, _workflow_name())

    new_key_client = await _connect_with_keys(settings, NEW_TEMPORAL_SECRET_KEY)
    with pytest.raises(InvalidToken):
        await _decode_schedule_args(new_key_client, schedule_id)

    await _connect_with_keys(settings, NEW_TEMPORAL_SECRET_KEY, [OLD_TEMPORAL_SECRET_KEY])

    await _call_command(
        "--format=csv",
        "--dry-run",
        "id",
        schedule_id,
    )

    captured = capsys.readouterr()
    assert _csv_output(captured.out) == [
        ["schedule_id", "status", "details"],
        [schedule_id, "skipped", "Dry-run"],
    ]

    description = await _describe_schedule(old_key_client, schedule_id)
    assert description.schedule.state.note == "existing note"
    with pytest.raises(InvalidToken):
        await _decode_schedule_args(new_key_client, schedule_id)
    assert await _decode_schedule_args(old_key_client, schedule_id) == [{"schedule_id": schedule_id}]


async def test_missing_schedule_reports_failure(capsys: pytest.CaptureFixture[str]) -> None:
    schedule_id = _schedule_id()

    await _call_command(
        "--format=csv",
        "id",
        schedule_id,
    )

    captured = capsys.readouterr()
    assert _csv_output(captured.out) == [
        ["schedule_id", "status", "details"],
        [schedule_id, "failed", "Schedule was not found"],
    ]


async def test_workflow_filter_updates_matching_schedules_only(
    settings, temporal: Client, schedule_ids: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    matching_workflow = _workflow_name()
    other_workflow = _workflow_name()
    matching_schedule_id = _schedule_id()
    other_schedule_id = _schedule_id()
    schedule_ids.extend([matching_schedule_id, other_schedule_id])
    old_key_client = await _connect_with_keys(settings, OLD_TEMPORAL_SECRET_KEY)
    await _create_schedule(old_key_client, matching_schedule_id, matching_workflow)
    await _create_schedule(old_key_client, other_schedule_id, other_workflow)
    await _wait_for_schedule_listed_by_workflow(temporal, matching_schedule_id, matching_workflow)

    new_key_client = await _connect_with_keys(settings, NEW_TEMPORAL_SECRET_KEY)
    with pytest.raises(InvalidToken):
        await _decode_schedule_args(new_key_client, matching_schedule_id)
    with pytest.raises(InvalidToken):
        await _decode_schedule_args(new_key_client, other_schedule_id)

    await _connect_with_keys(settings, NEW_TEMPORAL_SECRET_KEY, [OLD_TEMPORAL_SECRET_KEY])

    await _call_command(
        "--format=csv",
        "workflow",
        matching_workflow,
    )

    captured = capsys.readouterr()
    assert _csv_output(captured.out) == [
        ["schedule_id", "status", "details"],
        [matching_schedule_id, "success", ""],
    ]

    new_key_client = await _connect_with_keys(settings, NEW_TEMPORAL_SECRET_KEY)
    matching_description = await _describe_schedule(new_key_client, matching_schedule_id)
    other_description = await _describe_schedule(old_key_client, other_schedule_id)
    assert matching_description.schedule.state.note is not None
    assert "Schedule inputs re-encrypted on" in matching_description.schedule.state.note
    assert other_description.schedule.state.note == "existing note"
    assert await _decode_schedule_args(new_key_client, matching_schedule_id) == [{"schedule_id": matching_schedule_id}]
    with pytest.raises(InvalidToken):
        await _decode_schedule_args(new_key_client, other_schedule_id)
    assert await _decode_schedule_args(old_key_client, other_schedule_id) == [{"schedule_id": other_schedule_id}]
