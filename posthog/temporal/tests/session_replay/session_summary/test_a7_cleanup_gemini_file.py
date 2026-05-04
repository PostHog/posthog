import pytest
from unittest.mock import MagicMock, patch

from temporalio.testing import ActivityEnvironment

from posthog.temporal.session_replay.session_summary.activities.video_based.a7_cleanup_gemini_file import (
    cleanup_gemini_file_activity,
)


@pytest.mark.asyncio
async def test_deletes_file_via_gemini_client():
    fake_client = MagicMock()
    with patch(
        "posthog.temporal.session_replay.session_summary.activities.video_based.a7_cleanup_gemini_file.RawGenAIClient",
        return_value=fake_client,
    ):
        await ActivityEnvironment().run(cleanup_gemini_file_activity, "files/abc123", "session-1")

    fake_client.files.delete.assert_called_once_with(name="files/abc123")


@pytest.mark.asyncio
async def test_swallows_exceptions_so_workflow_can_continue():
    fake_client = MagicMock()
    fake_client.files.delete.side_effect = RuntimeError("gemini down")
    with patch(
        "posthog.temporal.session_replay.session_summary.activities.video_based.a7_cleanup_gemini_file.RawGenAIClient",
        return_value=fake_client,
    ):
        await ActivityEnvironment().run(cleanup_gemini_file_activity, "files/abc123", "session-1")
