import uuid

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.data_imports.workflow_activities.acquire_v3_lock import (
    AcquireV3LockActivityInputs,
    ReleaseV3LockActivityInputs,
    acquire_v3_pipeline_lock_activity,
    release_v3_pipeline_lock_activity,
)

TEAM_ID = 1
SCHEMA_ID = uuid.uuid4()
SOURCE_ID = uuid.uuid4()
WORKFLOW_RUN_ID = "run-abc-123"


def _make_inputs() -> AcquireV3LockActivityInputs:
    return AcquireV3LockActivityInputs(
        team_id=TEAM_ID,
        schema_id=SCHEMA_ID,
        source_id=SOURCE_ID,
    )


class TestAcquireV3PipelineLockActivity:
    @patch("posthog.temporal.data_imports.workflow_activities.acquire_v3_lock.activity")
    @patch(
        "posthog.temporal.data_imports.workflow_activities.acquire_v3_lock._is_pipeline_v3_enabled", return_value=False
    )
    @patch("posthog.temporal.data_imports.workflow_activities.acquire_v3_lock.ExternalDataSource")
    @patch("posthog.temporal.data_imports.workflow_activities.acquire_v3_lock.close_old_connections")
    @patch("posthog.temporal.data_imports.workflow_activities.acquire_v3_lock.bind_contextvars")
    def test_non_v3_returns_acquired_without_redis(
        self,
        _bind: MagicMock,
        _close: MagicMock,
        mock_source_model: MagicMock,
        mock_v3_check: MagicMock,
        mock_activity: MagicMock,
    ) -> None:
        mock_source = MagicMock()
        mock_source.source_type = "Stripe"
        mock_source_model.objects.get.return_value = mock_source

        result = acquire_v3_pipeline_lock_activity(_make_inputs())

        assert result.acquired is True
        assert result.is_v3 is False
        assert result.token == ""

    @pytest.mark.parametrize(
        "lock_acquired",
        [True, False],
        ids=["lock_free", "lock_held"],
    )
    @patch("posthog.temporal.data_imports.workflow_activities.acquire_v3_lock.acquire_v3_pipeline_lock")
    @patch("posthog.temporal.data_imports.workflow_activities.acquire_v3_lock.activity")
    @patch(
        "posthog.temporal.data_imports.workflow_activities.acquire_v3_lock._is_pipeline_v3_enabled", return_value=True
    )
    @patch("posthog.temporal.data_imports.workflow_activities.acquire_v3_lock.ExternalDataSource")
    @patch("posthog.temporal.data_imports.workflow_activities.acquire_v3_lock.close_old_connections")
    @patch("posthog.temporal.data_imports.workflow_activities.acquire_v3_lock.bind_contextvars")
    def test_v3_lock_result(
        self,
        _bind: MagicMock,
        _close: MagicMock,
        mock_source_model: MagicMock,
        mock_v3_check: MagicMock,
        mock_activity: MagicMock,
        mock_acquire: MagicMock,
        lock_acquired: bool,
    ) -> None:
        mock_source = MagicMock()
        mock_source.source_type = "Stripe"
        mock_source_model.objects.get.return_value = mock_source
        mock_activity.info.return_value.workflow_run_id = WORKFLOW_RUN_ID
        mock_acquire.return_value = lock_acquired

        result = acquire_v3_pipeline_lock_activity(_make_inputs())

        assert result.acquired is lock_acquired
        assert result.is_v3 is True
        assert result.token == WORKFLOW_RUN_ID
        mock_acquire.assert_called_once_with(TEAM_ID, str(SCHEMA_ID), WORKFLOW_RUN_ID)

    @patch("posthog.temporal.data_imports.workflow_activities.acquire_v3_lock.ExternalDataSource")
    @patch("posthog.temporal.data_imports.workflow_activities.acquire_v3_lock.close_old_connections")
    @patch("posthog.temporal.data_imports.workflow_activities.acquire_v3_lock.bind_contextvars")
    def test_source_not_found_returns_acquired(
        self,
        _bind: MagicMock,
        _close: MagicMock,
        mock_source_model: MagicMock,
    ) -> None:
        mock_source_model.DoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_source_model.objects.get.side_effect = mock_source_model.DoesNotExist

        result = acquire_v3_pipeline_lock_activity(_make_inputs())

        assert result.acquired is True
        assert result.is_v3 is False


class TestReleaseV3PipelineLockActivity:
    @patch("posthog.temporal.data_imports.workflow_activities.acquire_v3_lock.release_v3_pipeline_lock")
    @patch("posthog.temporal.data_imports.workflow_activities.acquire_v3_lock.bind_contextvars")
    def test_delegates_to_sync_lock(self, _bind: MagicMock, mock_release: MagicMock) -> None:
        inputs = ReleaseV3LockActivityInputs(
            team_id=TEAM_ID,
            schema_id=SCHEMA_ID,
            token=WORKFLOW_RUN_ID,
        )

        release_v3_pipeline_lock_activity(inputs)

        mock_release.assert_called_once_with(TEAM_ID, str(SCHEMA_ID), WORKFLOW_RUN_ID)
