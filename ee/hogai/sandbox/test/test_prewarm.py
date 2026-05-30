from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.http import StreamingHttpResponse

from parameterized import parameterized
from rest_framework import status

from posthog.models.user import User

from products.tasks.backend.models import Task, TaskRun

from ee.hogai.sandbox.executor import cancel_sandbox_prewarm, handle_sandbox_message, prewarm_sandbox_conversation
from ee.models.assistant import Conversation

EXECUTOR = "ee.hogai.sandbox.executor"


async def _fake_system_prompt(team: Any, user: Any) -> str:
    return "SYS"


class TestPrewarmSandboxConversation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="Sandbox chat",
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
        )

    def _prewarm(self) -> Any:
        with (
            patch(f"{EXECUTOR}.execute_task_processing_workflow") as workflow,
            patch(f"{EXECUTOR}._seed_sandbox_stream") as seed,
            patch(f"{EXECUTOR}.set_sandbox_mapping") as set_mapping,
            patch(f"{EXECUTOR}.build_posthog_ai_system_prompt", new=_fake_system_prompt),
        ):
            prewarm_sandbox_conversation(self.conversation, self.user, self.team)
        return workflow, seed, set_mapping

    def test_creates_task_and_warm_run_with_no_pending_message(self) -> None:
        workflow, seed, set_mapping = self._prewarm()

        self.conversation.refresh_from_db()
        self.assertIsNotNone(self.conversation.sandbox_task_id)
        self.assertIsNotNone(self.conversation.sandbox_run_id)

        task = Task.objects.get(id=self.conversation.sandbox_task_id)
        self.assertEqual(task.origin_product, Task.OriginProduct.POSTHOG_AI)
        self.assertIsNone(task.repository)
        self.assertEqual(task.created_by, self.user)

        run = TaskRun.objects.get(id=self.conversation.sandbox_run_id)
        self.assertFalse(run.is_terminal)
        self.assertEqual(run.state["mode"], "interactive")
        self.assertEqual(run.state["system_prompt"], "SYS")
        self.assertEqual(run.state["initial_permission_mode"], "default")
        # A warm Run carries NO pending message and NO attached context.
        self.assertNotIn("pending_user_message", run.state)
        self.assertNotIn("pending_user_artifact_ids", run.state)
        self.assertNotIn("attached_context", run.state)

        seed.assert_called_once_with(str(run.id))
        set_mapping.assert_called_once_with(str(self.conversation.id), str(task.id), str(run.id))

    def test_starts_workflow_with_full_scopes_and_no_pr(self) -> None:
        workflow, _, _ = self._prewarm()

        workflow.assert_called_once()
        self.assertEqual(workflow.call_args.kwargs["posthog_mcp_scopes"], "full")
        self.assertEqual(workflow.call_args.kwargs["create_pr"], False)
        self.assertEqual(workflow.call_args.kwargs["run_id"], str(self.conversation.sandbox_run_id))

    def test_idempotent_when_already_warm(self) -> None:
        self._prewarm()
        first_run_id = self.conversation.sandbox_run_id

        # Second POST while warm is a no-op — no new Task/Run, no second workflow.
        workflow, seed, set_mapping = self._prewarm()
        workflow.assert_not_called()
        seed.assert_not_called()
        set_mapping.assert_not_called()

        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.sandbox_run_id, first_run_id)
        self.assertEqual(TaskRun.objects.filter(task_id=self.conversation.sandbox_task_id).count(), 1)
        self.assertEqual(Task.objects.filter(id=self.conversation.sandbox_task_id).count(), 1)

    def test_reuses_existing_task_when_present(self) -> None:
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Sandbox chat",
            description="",
            origin_product=Task.OriginProduct.POSTHOG_AI,
        )
        self.conversation.sandbox_task_id = task.id
        self.conversation.save(update_fields=["sandbox_task_id"])

        self._prewarm()

        self.conversation.refresh_from_db()
        # Same Task reused; a fresh Run created under it.
        self.assertEqual(self.conversation.sandbox_task_id, task.id)
        self.assertEqual(Task.objects.filter(team=self.team).count(), 1)
        self.assertEqual(TaskRun.objects.filter(task=task).count(), 1)

    @parameterized.expand(
        [
            (TaskRun.Status.COMPLETED,),
            (TaskRun.Status.FAILED,),
            (TaskRun.Status.CANCELLED,),
        ]
    )
    def test_terminal_run_is_rewarmed_with_fresh_run(self, terminal_status: str) -> None:
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Sandbox chat",
            description="",
            origin_product=Task.OriginProduct.POSTHOG_AI,
        )
        old_run = TaskRun.objects.create(
            task=task, team=self.team, status=terminal_status, state={"mode": "interactive"}
        )
        self.conversation.sandbox_task_id = task.id
        self.conversation.sandbox_run_id = old_run.id
        self.conversation.save(update_fields=["sandbox_task_id", "sandbox_run_id"])

        workflow, _, _ = self._prewarm()

        workflow.assert_called_once()
        self.conversation.refresh_from_db()
        self.assertNotEqual(self.conversation.sandbox_run_id, old_run.id)
        new_run = TaskRun.objects.get(id=self.conversation.sandbox_run_id)
        self.assertFalse(new_run.is_terminal)

    def test_warmed_run_routes_followup_on_next_submit(self) -> None:
        self._prewarm()
        self.conversation.refresh_from_db()
        warm_run_id = self.conversation.sandbox_run_id

        with (
            patch(f"{EXECUTOR}.signal_task_followup_message") as signal,
            patch(f"{EXECUTOR}.execute_task_processing_workflow") as workflow,
            patch(f"{EXECUTOR}._seed_sandbox_stream"),
            patch(f"{EXECUTOR}.set_sandbox_mapping"),
            patch(f"{EXECUTOR}.get_sandbox_mapping", return_value=None),
            patch(f"{EXECUTOR}._get_latest_stream_id", return_value="0"),
            patch(f"{EXECUTOR}._emit_prompt_sent"),
            patch(f"{EXECUTOR}.build_posthog_ai_system_prompt", new=_fake_system_prompt),
            patch(
                f"{EXECUTOR}._make_streaming_response",
                side_effect=lambda factory: StreamingHttpResponse([b""], content_type="text/event-stream"),
            ),
        ):
            handle_sandbox_message(
                conversation=self.conversation,
                conversation_id=str(self.conversation.id),
                content="Why did conversions drop?",
                user=self.user,
                team=self.team,
                is_new_conversation=False,
                attached_context=[],
            )

        # In-progress warm Run → follow-up signal, reuse the same Run, no new Run/workflow.
        signal.assert_called_once()
        workflow.assert_not_called()
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.sandbox_run_id, warm_run_id)
        self.assertEqual(TaskRun.objects.filter(task_id=self.conversation.sandbox_task_id).count(), 1)


class TestCancelSandboxPrewarm(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Sandbox chat",
            description="",
            origin_product=Task.OriginProduct.POSTHOG_AI,
        )
        self.conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="Sandbox chat",
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
            sandbox_task_id=self.task.id,
        )

    def _warm_run(self, status_value: str = TaskRun.Status.IN_PROGRESS, sandbox_url: str | None = None) -> TaskRun:
        state: dict[str, str] = {"mode": "interactive"}
        if sandbox_url:
            state["sandbox_url"] = sandbox_url
        run = TaskRun.objects.create(task=self.task, team=self.team, status=status_value, state=state)
        self.conversation.sandbox_run_id = run.id
        self.conversation.save(update_fields=["sandbox_run_id"])
        return run

    def test_cancels_warm_run(self) -> None:
        run = self._warm_run(sandbox_url="https://sandbox.modal.run")
        with patch(f"{EXECUTOR}.cancel_sandbox_run", return_value="cancelled") as cancel:
            result = cancel_sandbox_prewarm(self.conversation, self.user, self.team)
        self.assertEqual(result, "cancelled")
        cancel.assert_called_once()
        self.assertEqual(cancel.call_args.args[0].id, run.id)

    def test_noop_when_run_still_booting(self) -> None:
        # A warm Run with no sandbox_url yet (still booting) cannot be proxy-cancelled — DELETE no-ops.
        self._warm_run()
        with patch(f"{EXECUTOR}.cancel_sandbox_run") as cancel:
            result = cancel_sandbox_prewarm(self.conversation, self.user, self.team)
        self.assertIsNone(result)
        cancel.assert_not_called()

    def test_noop_when_no_run(self) -> None:
        with patch(f"{EXECUTOR}.cancel_sandbox_run") as cancel:
            result = cancel_sandbox_prewarm(self.conversation, self.user, self.team)
        self.assertIsNone(result)
        cancel.assert_not_called()

    @parameterized.expand(
        [
            (TaskRun.Status.COMPLETED,),
            (TaskRun.Status.FAILED,),
            (TaskRun.Status.CANCELLED,),
        ]
    )
    def test_noop_when_run_terminal(self, terminal_status: str) -> None:
        self._warm_run(terminal_status)
        with patch(f"{EXECUTOR}.cancel_sandbox_run") as cancel:
            result = cancel_sandbox_prewarm(self.conversation, self.user, self.team)
        self.assertIsNone(result)
        cancel.assert_not_called()


class TestConversationPrewarmAction(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_user = User.objects.create_and_join(
            organization=self.organization,
            email="prewarm-other@posthog.com",
            password="password",
            first_name="Other",
        )

    def _sandbox_conversation(self, *, user: User | None = None) -> Conversation:
        return Conversation.objects.create(
            user=user or self.user,
            team=self.team,
            title="Sandbox chat",
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
        )

    def test_post_prewarm_returns_204_and_invokes_executor(self) -> None:
        conversation = self._sandbox_conversation()
        with patch("ee.api.conversation.prewarm_sandbox_conversation") as prewarm:
            response = self.client.post(f"/api/environments/{self.team.id}/conversations/{conversation.id}/prewarm/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        prewarm.assert_called_once()
        self.assertEqual(prewarm.call_args.args[0].id, conversation.id)

    def test_delete_prewarm_returns_204_and_invokes_cancel(self) -> None:
        conversation = self._sandbox_conversation()
        with patch("ee.api.conversation.cancel_sandbox_prewarm", return_value="cancelled") as cancel:
            response = self.client.delete(f"/api/environments/{self.team.id}/conversations/{conversation.id}/prewarm/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        cancel.assert_called_once()
        self.assertEqual(cancel.call_args.args[0].id, conversation.id)

    def test_langgraph_conversation_returns_400(self) -> None:
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="Langgraph chat",
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.LANGGRAPH,
        )
        with patch("ee.api.conversation.prewarm_sandbox_conversation") as prewarm:
            response = self.client.post(f"/api/environments/{self.team.id}/conversations/{conversation.id}/prewarm/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("sandbox-runtime only", response.json()["detail"])
        prewarm.assert_not_called()

    def test_cannot_prewarm_other_users_conversation(self) -> None:
        conversation = self._sandbox_conversation(user=self.other_user)
        with patch("ee.api.conversation.prewarm_sandbox_conversation") as prewarm:
            response = self.client.post(f"/api/environments/{self.team.id}/conversations/{conversation.id}/prewarm/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        prewarm.assert_not_called()
