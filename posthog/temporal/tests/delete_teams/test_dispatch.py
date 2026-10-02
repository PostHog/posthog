import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.client import WorkflowFailureError
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.delete_teams.dispatch import (
    ProjectDeletionCancellation,
    cancel_delete_project_data_workflow,
    start_delete_project_data_workflow,
)


def test_start_project_deletion_forwards_workflow_conflict_policy() -> None:
    client = AsyncMock()

    with patch(
        "posthog.temporal.delete_teams.dispatch.async_connect",
        new_callable=AsyncMock,
        return_value=client,
    ):
        start_delete_project_data_workflow(
            team_ids=[1],
            project_id=2,
            user_id=3,
            project_name="Test project",
            id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
        )

    client.start_workflow.assert_awaited_once()
    start_call = client.start_workflow.await_args
    assert start_call is not None
    assert start_call.kwargs["start_delay"] is None
    assert start_call.kwargs["id_conflict_policy"] == WorkflowIDConflictPolicy.TERMINATE_EXISTING


def test_cancel_project_deletion_waits_for_workflow_close() -> None:
    client = MagicMock()
    handle = AsyncMock()
    handle.result.side_effect = WorkflowFailureError(cause=RuntimeError("canceled"))
    client.get_workflow_handle.return_value = handle

    with patch(
        "posthog.temporal.delete_teams.dispatch.async_connect",
        new_callable=AsyncMock,
        return_value=client,
    ):
        outcome = cancel_delete_project_data_workflow(project_id=2)

    assert outcome == ProjectDeletionCancellation.CANCELED
    client.get_workflow_handle.assert_called_once_with("delete-project-2")
    handle.cancel.assert_awaited_once()
    handle.result.assert_awaited_once_with(follow_runs=False)


def test_cancel_project_deletion_accepts_a_workflow_that_is_not_running() -> None:
    client = MagicMock()
    handle = AsyncMock()
    handle.cancel.side_effect = RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b"")
    client.get_workflow_handle.return_value = handle

    with patch(
        "posthog.temporal.delete_teams.dispatch.async_connect",
        new_callable=AsyncMock,
        return_value=client,
    ):
        outcome = cancel_delete_project_data_workflow(project_id=2)

    assert outcome == ProjectDeletionCancellation.WORKFLOW_NOT_RUNNING
    handle.result.assert_not_awaited()


def test_cancel_project_deletion_reraises_other_temporal_errors() -> None:
    client = MagicMock()
    handle = AsyncMock()
    handle.cancel.side_effect = RPCError("temporal unavailable", RPCStatusCode.UNAVAILABLE, b"")
    client.get_workflow_handle.return_value = handle

    with (
        patch(
            "posthog.temporal.delete_teams.dispatch.async_connect",
            new_callable=AsyncMock,
            return_value=client,
        ),
        pytest.raises(RPCError),
    ):
        cancel_delete_project_data_workflow(project_id=2)
