from unittest.mock import AsyncMock, patch

from temporalio.common import WorkflowIDConflictPolicy

from posthog.temporal.delete_teams.dispatch import start_delete_project_data_workflow


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
