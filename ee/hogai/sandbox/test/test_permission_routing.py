from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.http import StreamingHttpResponse

from parameterized import parameterized
from rest_framework import exceptions, status

from products.tasks.backend.models import Task, TaskRun

from ee.hogai.sandbox.executor import handle_sandbox_message, send_permission_response
from ee.models.assistant import Conversation

EXECUTOR = "ee.hogai.sandbox.executor"


async def _fake_system_prompt(team: Any, user: Any) -> str:
    return "SYS"


class TestSendPermissionResponse(APIBaseTest):
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

    def test_forwards_permission_response_command_and_returns_body(self) -> None:
        run = self._run({"mode": "interactive", "sandbox_url": "http://localhost:9000"})
        agent_response = MagicMock(ok=True, status_code=200)
        agent_response.json.return_value = {"jsonrpc": "2.0", "result": {"ok": True}}

        with (
            patch(f"{EXECUTOR}.create_sandbox_connection_token", return_value="tok"),
            patch(
                f"{EXECUTOR}.TaskRunViewSet._proxy_command_to_agent_server",
                return_value=agent_response,
            ) as proxy,
        ):
            result = send_permission_response(
                run, self.user, request_id="req-1", option_id="allow_once", custom_input=None
            )

        self.assertEqual(result, {"jsonrpc": "2.0", "result": {"ok": True}})
        payload = proxy.call_args.kwargs["payload"]
        self.assertEqual(payload["method"], "permission_response")
        self.assertEqual(payload["params"]["requestId"], "req-1")
        self.assertEqual(payload["params"]["optionId"], "allow_once")
        # customInput is omitted when not provided.
        self.assertNotIn("customInput", payload["params"])

    def test_forwards_custom_input_when_present(self) -> None:
        run = self._run({"mode": "interactive", "sandbox_url": "http://localhost:9000"})
        agent_response = MagicMock(ok=True, status_code=200)
        agent_response.json.return_value = {}

        with (
            patch(f"{EXECUTOR}.create_sandbox_connection_token", return_value="tok"),
            patch(
                f"{EXECUTOR}.TaskRunViewSet._proxy_command_to_agent_server",
                return_value=agent_response,
            ) as proxy,
        ):
            send_permission_response(
                run, self.user, request_id="req-1", option_id="reject_with_feedback", custom_input="do this instead"
            )

        params = proxy.call_args.kwargs["payload"]["params"]
        self.assertEqual(params["customInput"], "do this instead")

    def test_without_sandbox_url_raises_validation_error(self) -> None:
        run = self._run({"mode": "interactive"})
        with self.assertRaises(exceptions.ValidationError):
            send_permission_response(run, self.user, request_id="r", option_id="allow_once")

    def test_rejects_disallowed_sandbox_url(self) -> None:
        run = self._run({"mode": "interactive", "sandbox_url": "http://evil.example.com:9000"})
        with self.assertRaises(exceptions.ValidationError):
            send_permission_response(run, self.user, request_id="r", option_id="allow_once")

    def test_agent_rejection_raises_api_exception(self) -> None:
        run = self._run({"mode": "interactive", "sandbox_url": "http://localhost:9000"})
        agent_response = MagicMock(ok=False, status_code=400)

        with (
            patch(f"{EXECUTOR}.create_sandbox_connection_token", return_value="tok"),
            patch(
                f"{EXECUTOR}.TaskRunViewSet._proxy_command_to_agent_server",
                return_value=agent_response,
            ),
        ):
            with self.assertRaises(exceptions.APIException):
                send_permission_response(run, self.user, request_id="r", option_id="allow_once")


class TestConversationPermissionAction(APIBaseTest):
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

    def _run(self) -> TaskRun:
        return TaskRun.objects.create(
            task=self.task, team=self.team, status=TaskRun.Status.IN_PROGRESS, state={"mode": "interactive"}
        )

    def test_permission_routes_sandbox_branch_and_persists_decision(self) -> None:
        run = self._run()
        conversation = self._sandbox_conversation(run)

        with patch("ee.api.conversation.send_permission_response", return_value={"result": {"ok": True}}) as send:
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/permission/",
                {
                    "requestId": "req-1",
                    "optionId": "allow_once",
                    "options": [{"optionId": "allow_once", "name": "Allow", "kind": "allow_once"}],
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"result": {"ok": True}})
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0].id, run.id)
        self.assertEqual(send.call_args.kwargs["request_id"], "req-1")
        self.assertEqual(send.call_args.kwargs["option_id"], "allow_once")

        # options[] persisted inside the existing approval_decisions JSON — no new column/migration.
        conversation.refresh_from_db()
        decision = conversation.approval_decisions["req-1"]
        self.assertEqual(decision["decision_status"], "approved")
        self.assertEqual(decision["option_id"], "allow_once")
        self.assertEqual(decision["options"][0]["kind"], "allow_once")
        self.assertEqual(decision["runtime"], "sandbox")

    @parameterized.expand(
        [
            ("reject", "rejected"),
            ("reject_with_feedback", "rejected"),
            ("allow_always", "approved"),
        ]
    )
    def test_decision_status_from_option_kind(self, kind: str, expected_status: str) -> None:
        run = self._run()
        conversation = self._sandbox_conversation(run)

        with patch("ee.api.conversation.send_permission_response", return_value={}):
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/permission/",
                {
                    "requestId": "req-2",
                    "optionId": "opt",
                    "options": [{"optionId": "opt", "kind": kind}],
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        conversation.refresh_from_db()
        self.assertEqual(conversation.approval_decisions["req-2"]["decision_status"], expected_status)

    def test_langgraph_conversation_returns_400(self) -> None:
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="Langgraph chat",
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.LANGGRAPH,
        )

        with patch("ee.api.conversation.send_permission_response") as send:
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/permission/",
                {"requestId": "r", "optionId": "allow_once"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        send.assert_not_called()

    def test_permission_without_run_returns_404(self) -> None:
        conversation = self._sandbox_conversation(None)
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/permission/",
            {"requestId": "r", "optionId": "allow_once"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_missing_request_id_returns_400(self) -> None:
        run = self._run()
        conversation = self._sandbox_conversation(run)
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/permission/",
            {"optionId": "allow_once"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_resolve_other_users_conversation(self) -> None:
        other_user = self._create_user("other-permission@posthog.com")
        run = self._run()
        conversation = Conversation.objects.create(
            user=other_user,
            team=self.team,
            title="Other's sandbox chat",
            type=Conversation.Type.ASSISTANT,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
            sandbox_task_id=self.task.id,
            sandbox_run_id=run.id,
        )

        with patch("ee.api.conversation.send_permission_response") as send:
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/permission/",
                {"requestId": "r", "optionId": "allow_once"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        send.assert_not_called()


class TestTerminalResumeRace(APIBaseTest):
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

    def _terminal_run(self) -> TaskRun:
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            state={"mode": "interactive", "snapshot_external_id": "snap-1"},
        )
        self.conversation.sandbox_run_id = run.id
        self.conversation.save(update_fields=["sandbox_run_id"])
        return run

    def _call(self) -> Any:
        with (
            patch(f"{EXECUTOR}.signal_task_followup_message"),
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
                content="Resume",
                user=self.user,
                team=self.team,
                is_new_conversation=False,
                attached_context=[],
            )
        return workflow

    def test_first_writer_creates_single_resume_run_and_starts_workflow(self) -> None:
        terminal = self._terminal_run()
        workflow = self._call()

        new_runs = TaskRun.objects.filter(task=self.task).exclude(id=terminal.id)
        self.assertEqual(new_runs.count(), 1)
        workflow.assert_called_once()
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.sandbox_run_id, new_runs.get().id)

    def test_second_writer_reuses_existing_resume_run_no_duplicate(self) -> None:
        # Simulate the first tab having already created and re-pointed to a non-terminal resume Run.
        terminal = self._terminal_run()
        existing_resume = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"mode": "interactive", "resume_from_run_id": str(terminal.id)},
        )
        # The in-memory conversation still believes the terminal run is current (stale read), but the
        # DB row already points at the resume run — exactly the second-tab race window.
        Conversation.objects.filter(pk=self.conversation.pk).update(sandbox_run_id=existing_resume.id)

        workflow = self._call()

        # No new Run created — the second writer reuses the existing resume Run under the lock.
        all_runs = TaskRun.objects.filter(task=self.task)
        self.assertEqual(all_runs.count(), 2)
        # And it never starts a duplicate workflow.
        workflow.assert_not_called()
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.sandbox_run_id, existing_resume.id)

    @parameterized.expand(
        [
            (TaskRun.Status.COMPLETED,),
            (TaskRun.Status.FAILED,),
            (TaskRun.Status.CANCELLED,),
        ]
    )
    def test_terminal_concurrent_run_is_not_reused(self, terminal_status: str) -> None:
        # If the DB-current run is itself terminal (e.g. both tabs hit terminal runs), the writer must
        # create a fresh resume Run rather than reuse a dead one.
        terminal = self._terminal_run()
        other_terminal = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=terminal_status,
            state={"mode": "interactive", "snapshot_external_id": "snap-1"},
        )
        Conversation.objects.filter(pk=self.conversation.pk).update(sandbox_run_id=other_terminal.id)

        workflow = self._call()

        # A new resume Run is created because the DB-current run was terminal, not reusable.
        new_runs = TaskRun.objects.filter(task=self.task).exclude(id__in=[terminal.id, other_terminal.id])
        self.assertEqual(new_runs.count(), 1)
        workflow.assert_called_once()


class TestExecutorSourceGuards(APIBaseTest):
    def test_permission_proxy_uses_permission_response_method_and_lock(self) -> None:
        from pathlib import Path

        source = Path(__file__).resolve().parent.parent / "executor.py"
        text = source.read_text()
        # The permission proxy must use the agent-server's permission_response method, not user_message.
        self.assertIn('"method": "permission_response"', text)
        # The terminal-then-resume race fix serializes on the Conversation row.
        self.assertIn("select_for_update", text)
