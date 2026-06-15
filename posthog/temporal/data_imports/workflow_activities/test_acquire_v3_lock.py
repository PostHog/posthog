import uuid

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.data_imports.workflow_activities.acquire_v3_lock import (
    AcquireV3LockActivityInputs,
    CheckPipelineVersionActivityInputs,
    ReleaseV3LockActivityInputs,
    acquire_v3_pipeline_lock_activity,
    check_pipeline_version_activity,
    release_v3_pipeline_lock_activity,
)

TEAM_ID = 1
SCHEMA_ID = uuid.uuid4()
SOURCE_ID = uuid.uuid4()
WORKFLOW_RUN_ID = "run-abc-123"

MODULE = "posthog.temporal.data_imports.workflow_activities.acquire_v3_lock"


class TestCheckPipelineVersionActivity:
    @pytest.mark.parametrize(
        "ff_enabled, expected_is_v3",
        [
            (False, False),
            (True, True),
        ],
        ids=["v2", "v3"],
    )
    @patch(f"{MODULE}.is_pipeline_v3_enabled")
    @patch(f"{MODULE}.ExternalDataSource")
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.bind_contextvars")
    def test_returns_ff_result(
        self,
        _bind: MagicMock,
        _close: MagicMock,
        mock_source_model: MagicMock,
        mock_v3_check: MagicMock,
        ff_enabled: bool,
        expected_is_v3: bool,
    ) -> None:
        mock_source = MagicMock()
        mock_source.source_type = "Stripe"
        mock_source_model.objects.get.return_value = mock_source
        mock_v3_check.return_value = ff_enabled

        result = check_pipeline_version_activity(
            CheckPipelineVersionActivityInputs(team_id=TEAM_ID, source_id=SOURCE_ID)
        )

        assert result.is_v3 is expected_is_v3
        mock_v3_check.assert_called_once_with(TEAM_ID, "Stripe")

    @patch(f"{MODULE}.ExternalDataSource")
    @patch(f"{MODULE}.close_old_connections")
    @patch(f"{MODULE}.bind_contextvars")
    def test_source_not_found_returns_not_v3(
        self,
        _bind: MagicMock,
        _close: MagicMock,
        mock_source_model: MagicMock,
    ) -> None:
        mock_source_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_source_model.objects.get.side_effect = mock_source_model.DoesNotExist

        result = check_pipeline_version_activity(
            CheckPipelineVersionActivityInputs(team_id=TEAM_ID, source_id=SOURCE_ID)
        )

        assert result.is_v3 is False


class TestAcquireV3PipelineLockActivity:
    @pytest.mark.parametrize(
        "lock_acquired",
        [True, False],
        ids=["lock_free", "lock_held"],
    )
    @patch(f"{MODULE}.acquire_v3_pipeline_lock")
    @patch(f"{MODULE}.activity")
    @patch(f"{MODULE}.bind_contextvars")
    def test_lock_result(
        self,
        _bind: MagicMock,
        mock_activity: MagicMock,
        mock_acquire: MagicMock,
        lock_acquired: bool,
    ) -> None:
        mock_activity.info.return_value.workflow_run_id = WORKFLOW_RUN_ID
        mock_acquire.return_value = lock_acquired

        result = acquire_v3_pipeline_lock_activity(AcquireV3LockActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID))

        assert result.acquired is lock_acquired
        assert result.token == WORKFLOW_RUN_ID
        mock_acquire.assert_called_once_with(TEAM_ID, str(SCHEMA_ID), WORKFLOW_RUN_ID)

    @patch(f"{MODULE}.activity")
    @patch(f"{MODULE}.bind_contextvars")
    def test_empty_workflow_run_id_fails_closed(
        self,
        _bind: MagicMock,
        mock_activity: MagicMock,
    ) -> None:
        mock_activity.info.return_value.workflow_run_id = ""

        result = acquire_v3_pipeline_lock_activity(AcquireV3LockActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID))

        assert result.acquired is False
        assert result.token == ""


class TestReleaseV3PipelineLockActivity:
    @patch(f"{MODULE}.release_v3_pipeline_lock")
    @patch(f"{MODULE}.bind_contextvars")
    def test_delegates_to_sync_lock(self, _bind: MagicMock, mock_release: MagicMock) -> None:
        inputs = ReleaseV3LockActivityInputs(
            team_id=TEAM_ID,
            schema_id=SCHEMA_ID,
            token=WORKFLOW_RUN_ID,
        )

        release_v3_pipeline_lock_activity(inputs)

        mock_release.assert_called_once_with(TEAM_ID, str(SCHEMA_ID), WORKFLOW_RUN_ID)
