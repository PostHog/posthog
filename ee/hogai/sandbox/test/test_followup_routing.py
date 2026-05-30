from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.http import StreamingHttpResponse

from parameterized import parameterized
from rest_framework import exceptions, status

from products.tasks.backend.models import Task, TaskRun

from ee.hogai.sandbox.context_wrapper import AttachedContext
from ee.hogai.sandbox.executor import cancel_sandbox_run, handle_sandbox_message
from ee.models.assistant import Conversation

EXECUTOR = "ee.hogai.sandbox.executor"


async def _fake_system_prompt(team: Any, user: Any) -> str:
    return "SYS"


class TestSandboxFollowupRouting(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Sandbox chat",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self.conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="Sandbox chat",
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
            sandbox_task_id=self.task.id,
        )

    def _make_run(self, status_value: str, state: dict[str, Any] | None = None) -> TaskRun:
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=status_value,
            state=state or {"mode": "interactive"},
        )
        self.conversation.sandbox_run_id = run.id
        self.conversation.save(update_fields=["sandbox_run_id"])
        return run

    def _call(self, content: str, attached_context: list[AttachedContext] | None = None) -> Any:
        # Patch every side-effecting boundary so only the routing decision is exercised.
        with (
            patch(f"{EXECUTOR}.signal_task_followup_message") as signal,
            patch(f"{EXECUTOR}.execute_task_processing_workflow") as workflow,
            patch(f"{EXECUTOR}._seed_sandbox_stream"),
            patch(f"{EXECUTOR}.set_sandbox_mapping"),
            # Redis-backed mapping returns None in tests; the executor falls back to the
            # conversation's sandbox_task_id / sandbox_run_id fields.
            patch(f"{EXECUTOR}.get_sandbox_mapping", return_value=None),
            patch(f"{EXECUTOR}._get_latest_stream_id", return_value="0"),
            patch(f"{EXECUTOR}._emit_prompt_sent") as emit,
            patch(f"{EXECUTOR}.build_posthog_ai_system_prompt", new=_fake_system_prompt),
            patch(
                f"{EXECUTOR}._make_streaming_response",
                side_effect=lambda factory: StreamingHttpResponse([b""], content_type="text/event-stream"),
            ),
        ):
            response = handle_sandbox_message(
                conversation=self.conversation,
                conversation_id=str(self.conversation.id),
                content=content,
                user=self.user,
                team=self.team,
                is_new_conversation=False,
                attached_context=attached_context or [],
            )
        return response, signal, workflow, emit

    def test_in_progress_followup_signals_and_reuses_run(self) -> None:
        run = self._make_run(TaskRun.Status.IN_PROGRESS)
        _, signal, workflow, emit = self._call("More detail please")

        signal.assert_called_once()
        called_workflow_id, called_content, called_artifacts = signal.call_args.args
        self.assertEqual(called_workflow_id, run.workflow_id)
        self.assertEqual(called_artifacts, [])
        # In-progress reuses the same Run; no new Run, no workflow start.
        workflow.assert_not_called()
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.sandbox_run_id, run.id)
        self.assertEqual(TaskRun.objects.filter(task=self.task).count(), 1)

    @parameterized.expand(
        [
            (TaskRun.Status.COMPLETED,),
            (TaskRun.Status.FAILED,),
            (TaskRun.Status.CANCELLED,),
        ]
    )
    def test_terminal_followup_creates_resume_run_with_full_scopes(self, terminal_status: str) -> None:
        run = self._make_run(terminal_status, state={"mode": "interactive", "snapshot_external_id": "snap-1"})
        _, signal, workflow, emit = self._call("Resume from here")

        # Terminal Run never signals; it spins up a fresh resume Run instead.
        signal.assert_not_called()
        workflow.assert_called_once()
        self.assertEqual(workflow.call_args.kwargs["posthog_mcp_scopes"], "full")
        self.assertEqual(workflow.call_args.kwargs["create_pr"], False)

        new_runs = TaskRun.objects.filter(task=self.task).exclude(id=run.id)
        self.assertEqual(new_runs.count(), 1)
        new_run = new_runs.get()
        self.assertEqual(new_run.state["resume_from_run_id"], str(run.id))
        self.assertEqual(new_run.state["snapshot_external_id"], "snap-1")
        self.assertIn("pending_user_message", new_run.state)

        # Conversation re-points to the new Run.
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.sandbox_run_id, new_run.id)
        # Workflow started against the new Run, not the terminal one.
        self.assertEqual(workflow.call_args.kwargs["run_id"], str(new_run.id))

    def test_terminal_followup_repoints_with_narrow_update_fields(self) -> None:
        self._make_run(TaskRun.Status.COMPLETED, state={"mode": "interactive", "snapshot_external_id": "snap-1"})
        original_task_id = self.conversation.sandbox_task_id

        with patch.object(Conversation, "save", autospec=True) as save_spy:
            self._call("Resume")

        repoint_calls = [c for c in save_spy.call_args_list if c.kwargs.get("update_fields") == ["sandbox_run_id"]]
        self.assertTrue(repoint_calls, "expected a save() narrowed to update_fields=['sandbox_run_id']")
        # The task pointer is never touched on the re-point.
        self.assertEqual(self.conversation.sandbox_task_id, original_task_id)

    def test_terminal_followup_without_snapshot_raises(self) -> None:
        self._make_run(TaskRun.Status.COMPLETED, state={"mode": "interactive"})
        with self.assertRaises(exceptions.ValidationError):
            self._call("Resume")

    def test_followup_wraps_content_with_attached_context(self) -> None:
        run = self._make_run(TaskRun.Status.IN_PROGRESS)
        _, signal, _, _ = self._call(
            "Look here", attached_context=[AttachedContext(type="dashboard", id=123, name="Marketing Funnel")]
        )
        wrapped = signal.call_args.args[1]
        self.assertIn("<posthog_context>", wrapped)
        self.assertIn("Dashboard #123", wrapped)
        self.assertIn("Look here", wrapped)
        # Full undeduped structured context is persisted on the reused Run.
        run.refresh_from_db()
        self.assertEqual(run.state["attached_context"], [{"type": "dashboard", "id": 123, "name": "Marketing Funnel"}])

    def test_terminal_followup_persists_undeduped_context_on_new_run(self) -> None:
        run = self._make_run(TaskRun.Status.COMPLETED, state={"mode": "interactive", "snapshot_external_id": "snap-1"})
        self._call("Go", attached_context=[AttachedContext(type="insight", id="abc", name="Daily Signups")])
        new_run = TaskRun.objects.filter(task=self.task).exclude(id=run.id).get()
        self.assertEqual(new_run.state["attached_context"], [{"type": "insight", "id": "abc", "name": "Daily Signups"}])
        self.assertEqual(new_run.state["system_prompt"], "SYS")

    @parameterized.expand(
        [
            (TaskRun.Status.IN_PROGRESS, False),
            (TaskRun.Status.COMPLETED, True),
        ]
    )
    def test_prompt_sent_telemetry_just_created_run(self, run_status: str, expected_just_created: bool) -> None:
        self._make_run(run_status, state={"mode": "interactive", "snapshot_external_id": "snap-1"})
        _, _, _, emit = self._call("Hi")
        emit.assert_called_once()
        self.assertEqual(emit.call_args.kwargs["just_created_run"], expected_just_created)

    def test_refresh_session_is_never_used(self) -> None:
        from pathlib import Path

        source = Path(__file__).resolve().parent.parent / "executor.py"
        self.assertNotIn("refresh_session", source.read_text())


class TestPromptSentTelemetry(APIBaseTest):
    def test_emit_prompt_sent_shapes_event(self) -> None:
        from ee.hogai.sandbox.executor import PROMPT_SENT_EVENT, _emit_prompt_sent

        with patch("ee.hogai.sandbox.executor.posthoganalytics.capture") as capture:
            _emit_prompt_sent(
                team=self.team,
                user=self.user,
                conversation_id="conv-1",
                attached_context=[AttachedContext(type="dashboard", id=1)],
                just_created_run=True,
            )
        capture.assert_called_once()
        self.assertEqual(capture.call_args.kwargs["event"], PROMPT_SENT_EVENT)
        props = capture.call_args.kwargs["properties"]
        self.assertEqual(props["execution_type"], "sandbox")
        self.assertEqual(props["agent_runtime"], "sandbox")
        self.assertTrue(props["just_created_run"])
        self.assertTrue(props["has_attached_context"])
        self.assertEqual(props["attached_context_count"], 1)


class TestCancelSandboxRun(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Sandbox chat",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def _run(self, state: dict[str, Any]) -> TaskRun:
        return TaskRun.objects.create(task=self.task, team=self.team, status=TaskRun.Status.IN_PROGRESS, state=state)

    def test_cancel_proxies_command_and_returns_status(self) -> None:
        run = self._run({"mode": "interactive", "sandbox_url": "http://localhost:9000"})
        agent_response = MagicMock(ok=True, status_code=200)
        agent_response.json.return_value = {"status": "cancelled"}

        with (
            patch("ee.hogai.sandbox.executor.create_sandbox_connection_token", return_value="tok"),
            patch(
                "ee.hogai.sandbox.executor.TaskRunViewSet._proxy_command_to_agent_server",
                return_value=agent_response,
            ) as proxy,
        ):
            result = cancel_sandbox_run(run, self.user)

        self.assertEqual(result, "cancelled")
        payload = proxy.call_args.kwargs["payload"]
        self.assertEqual(payload["method"], "cancel")

    def test_cancel_without_sandbox_url_raises_validation_error(self) -> None:
        run = self._run({"mode": "interactive"})
        with self.assertRaises(exceptions.ValidationError):
            cancel_sandbox_run(run, self.user)

    def test_cancel_rejects_disallowed_sandbox_url(self) -> None:
        run = self._run({"mode": "interactive", "sandbox_url": "http://evil.example.com:9000"})
        with self.assertRaises(exceptions.ValidationError):
            cancel_sandbox_run(run, self.user)


class TestConversationCancelSandboxBranch(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Sandbox chat",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def _sandbox_conversation(self, run: TaskRun | None) -> Conversation:
        return Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="Sandbox chat",
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
            sandbox_task_id=self.task.id,
            sandbox_run_id=run.id if run else None,
        )

    def test_cancel_routes_sandbox_branch_to_command_cancel(self) -> None:
        run = TaskRun.objects.create(
            task=self.task, team=self.team, status=TaskRun.Status.IN_PROGRESS, state={"mode": "interactive"}
        )
        conversation = self._sandbox_conversation(run)

        with patch("ee.api.conversation.cancel_sandbox_run", return_value="cancelled") as cancel:
            response = self.client.patch(f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/")

        cancel.assert_called_once()
        self.assertEqual(cancel.call_args.args[0].id, run.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"run_status": "cancelled"})

    def test_cancel_sandbox_without_run_returns_404(self) -> None:
        conversation = self._sandbox_conversation(None)
        response = self.client.patch(f"/api/environments/{self.team.id}/conversations/{conversation.id}/cancel/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
