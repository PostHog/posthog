from __future__ import annotations

from uuid import UUID

from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from products.deployments.backend.adapters.temporal import (
    DEPLOYMENT_BUILD_WORKFLOW,
    TemporalWorkflowAdapter,
    WorkflowError,
)
from products.deployments.backend.domain.contracts import BuildInput
from products.deployments.backend.domain.trigger import TriggerKind

BUILD_INPUT = BuildInput(
    deployment_id=UUID("00000000-0000-7000-8000-000000000001"),
    project_id=UUID("00000000-0000-7000-8000-000000000002"),
    team_id=1,
    repo_url="https://github.com/example/repo",
    branch="main",
    commit_sha="abc123",
    github_access_token=None,
    build_command=None,
    output_dir="dist",
    framework=None,
    inject_posthog_snippet=False,
    cloudflare_project_name="hogdev-1-myapp",
    trigger_kind=TriggerKind.GIT,
)


def _make_rpc_error(message: str, status: RPCStatusCode = RPCStatusCode.UNKNOWN) -> RPCError:
    # RPCError's third positional arg (raw_proto) is bytes, not str.
    return RPCError(message, status, b"")


@override_settings(DEPLOYMENTS_TASK_QUEUE="deployments-task-queue", TEMPORAL_WORKFLOW_MAX_ATTEMPTS="5")
class TestTemporalWorkflowAdapter(SimpleTestCase):
    @patch("products.deployments.backend.adapters.temporal.sync_connect")
    def test_start_build_invokes_temporal_with_correct_arguments(self, mock_connect: MagicMock) -> None:
        handle = MagicMock()
        handle.first_execution_run_id = "run-abc"
        handle.result_run_id = None
        client = MagicMock()
        client.start_workflow = AsyncMock(return_value=handle)
        mock_connect.return_value = client

        result = TemporalWorkflowAdapter().start_build(workflow_input=BUILD_INPUT)

        self.assertEqual(result.workflow_id, f"deployment-{BUILD_INPUT.deployment_id}")
        self.assertEqual(result.run_id, "run-abc")
        client.start_workflow.assert_awaited_once()
        call = client.start_workflow.await_args
        self.assertEqual(call.args[0], DEPLOYMENT_BUILD_WORKFLOW)
        self.assertEqual(call.args[1], BUILD_INPUT)
        self.assertEqual(call.kwargs["id"], f"deployment-{BUILD_INPUT.deployment_id}")
        self.assertEqual(call.kwargs["task_queue"], "deployments-task-queue")
        self.assertEqual(call.kwargs["retry_policy"].maximum_attempts, 5)

    @patch("products.deployments.backend.adapters.temporal.sync_connect")
    def test_start_build_prefers_result_run_id_when_available(self, mock_connect: MagicMock) -> None:
        handle = MagicMock()
        handle.result_run_id = "run-result"
        handle.first_execution_run_id = "run-first"
        client = MagicMock()
        client.start_workflow = AsyncMock(return_value=handle)
        mock_connect.return_value = client

        result = TemporalWorkflowAdapter().start_build(workflow_input=BUILD_INPUT)
        self.assertEqual(result.run_id, "run-result")

    @patch("products.deployments.backend.adapters.temporal.sync_connect")
    def test_start_build_wraps_rpc_error_in_workflow_error(self, mock_connect: MagicMock) -> None:
        client = MagicMock()
        client.start_workflow = AsyncMock(side_effect=_make_rpc_error("temporal unreachable"))
        mock_connect.return_value = client

        with self.assertRaises(WorkflowError) as cm:
            TemporalWorkflowAdapter().start_build(workflow_input=BUILD_INPUT)
        self.assertIn("temporal unreachable", str(cm.exception))

    @patch("products.deployments.backend.adapters.temporal.sync_connect")
    def test_start_build_wraps_workflow_already_started_in_workflow_error(self, mock_connect: MagicMock) -> None:
        # `WorkflowAlreadyStartedError` doesn't inherit from `RPCError` —
        # exercised separately so the catch in start_build stays correct.
        client = MagicMock()
        client.start_workflow = AsyncMock(
            side_effect=WorkflowAlreadyStartedError(workflow_id="deployment-abc", workflow_type="deployment-build")
        )
        mock_connect.return_value = client

        with self.assertRaises(WorkflowError) as cm:
            TemporalWorkflowAdapter().start_build(workflow_input=BUILD_INPUT)
        self.assertIn("already running", str(cm.exception))

    def test_start_build_raises_when_task_queue_setting_missing(self) -> None:
        with override_settings(DEPLOYMENTS_TASK_QUEUE=""):
            with self.assertRaises(WorkflowError) as cm:
                TemporalWorkflowAdapter().start_build(workflow_input=BUILD_INPUT)
            self.assertIn("DEPLOYMENTS_TASK_QUEUE", str(cm.exception))

    @patch("products.deployments.backend.adapters.temporal.sync_connect")
    def test_signal_cancel_calls_handle_cancel(self, mock_connect: MagicMock) -> None:
        handle = MagicMock()
        handle.cancel = AsyncMock()
        client = MagicMock()
        client.get_workflow_handle = MagicMock(return_value=handle)
        mock_connect.return_value = client

        TemporalWorkflowAdapter().signal_cancel(workflow_id="deployment-abc")

        client.get_workflow_handle.assert_called_once_with("deployment-abc")
        handle.cancel.assert_awaited_once()

    # Drive signal_cancel's NOT_FOUND detection from the structured
    # RPCStatusCode rather than the message string — including the case
    # where the message *contains* "not found" but the status is wrong
    # (which should still raise), proving the substring-match path is
    # gone.
    @parameterized.expand(
        [
            ("not_found_with_canonical_message", RPCStatusCode.NOT_FOUND, "workflow execution not found", False),
            ("not_found_with_different_message", RPCStatusCode.NOT_FOUND, "execution does not exist", False),
            ("unknown_error", RPCStatusCode.UNKNOWN, "internal server error", True),
            ("unavailable_with_not_found_substring", RPCStatusCode.UNAVAILABLE, "task queue not found", True),
        ]
    )
    @patch("products.deployments.backend.adapters.temporal.sync_connect")
    def test_signal_cancel_status_code_drives_behaviour(
        self, _name: str, status: RPCStatusCode, message: str, should_raise: bool, mock_connect: MagicMock
    ) -> None:
        handle = MagicMock()
        handle.cancel = AsyncMock(side_effect=_make_rpc_error(message, status))
        client = MagicMock()
        client.get_workflow_handle = MagicMock(return_value=handle)
        mock_connect.return_value = client

        if should_raise:
            with self.assertRaises(WorkflowError) as cm:
                TemporalWorkflowAdapter().signal_cancel(workflow_id="deployment-abc")
            self.assertIn(message, str(cm.exception))
        else:
            # No exception — the workflow finished or never existed.
            TemporalWorkflowAdapter().signal_cancel(workflow_id="deployment-abc")
