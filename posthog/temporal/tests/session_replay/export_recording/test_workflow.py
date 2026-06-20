from uuid import UUID

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.temporal.session_replay.export_recording.activities import mark_export_failed
from posthog.temporal.session_replay.export_recording.types import ExportRecordingInput, MarkExportFailedInput
from posthog.temporal.session_replay.export_recording.workflow import ExportRecordingWorkflow

WORKFLOW = "posthog.temporal.session_replay.export_recording.workflow.workflow"


def test_export_recording_workflow_parse_inputs():
    result = ExportRecordingWorkflow.parse_inputs(['{"exported_recording_id": "01938a67-1234-7000-8000-000000000001"}'])
    assert result.exported_recording_id == UUID("01938a67-1234-7000-8000-000000000001")
    assert result.redis_config.redis_url is None


def test_export_recording_workflow_parse_inputs_string_uuid():
    result = ExportRecordingWorkflow.parse_inputs(['{"exported_recording_id": "01938a67-5678-7000-8000-000000000002"}'])
    assert result.exported_recording_id == UUID("01938a67-5678-7000-8000-000000000002")


def test_export_recording_workflow_parse_inputs_with_redis_config():
    result = ExportRecordingWorkflow.parse_inputs(
        [
            '{"exported_recording_id": "01938a67-1234-7000-8000-000000000001", '
            '"redis_config": {"redis_url": "redis://custom-redis:6380", "redis_ttl": 7200}}'
        ]
    )
    assert result.exported_recording_id == UUID("01938a67-1234-7000-8000-000000000001")
    assert result.redis_config.redis_url == "redis://custom-redis:6380"
    assert result.redis_config.redis_ttl == 7200


@pytest.mark.asyncio
async def test_export_recording_workflow_marks_failed_on_export_error():
    recording_id = UUID("01938a67-1234-7000-8000-000000000099")
    marked: list[MarkExportFailedInput] = []

    async def fake_execute_activity(activity_fn, arg, **kwargs):
        if activity_fn is mark_export_failed:
            marked.append(arg)
            return None
        raise RuntimeError("no column 'sharded_events.properties_group_ai_large'")

    with (
        patch(f"{WORKFLOW}.execute_activity", new=AsyncMock(side_effect=fake_execute_activity)),
        patch(f"{WORKFLOW}.logger", new=MagicMock()),
    ):
        with pytest.raises(RuntimeError):
            await ExportRecordingWorkflow().run(ExportRecordingInput(exported_recording_id=recording_id))

    # the export is marked failed (not left RUNNING) with a non-empty error recorded
    assert len(marked) == 1
    assert marked[0].exported_recording_id == recording_id
    assert marked[0].error_message


@pytest.mark.asyncio
async def test_export_recording_workflow_reraises_original_when_marking_also_fails():
    recording_id = UUID("01938a67-1234-7000-8000-000000000098")
    original = RuntimeError("original export error")

    # the failure handler itself fails (e.g. DB unreachable) - this must not mask the original error
    async def fake_execute_activity(activity_fn, arg, **kwargs):
        if activity_fn is mark_export_failed:
            raise RuntimeError("could not reach the database")
        raise original

    with (
        patch(f"{WORKFLOW}.execute_activity", new=AsyncMock(side_effect=fake_execute_activity)),
        patch(f"{WORKFLOW}.logger", new=MagicMock()),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            await ExportRecordingWorkflow().run(ExportRecordingInput(exported_recording_id=recording_id))

    # the original export error propagates, not the secondary marking failure
    assert exc_info.value is original
