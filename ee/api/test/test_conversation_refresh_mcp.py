from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.posthog_ai.backend.message_routing import SandboxBusyError, SandboxCommandError, SandboxRefreshMcpResult
from products.posthog_ai.backend.models.assistant import Conversation
from products.tasks.backend.models import Task, TaskRun

ROUTING_PATH = "ee.api.conversation.MessageRoutingService.refresh_mcp"


class TestConversationRefreshMcp(APIBaseTest):
    def _sandbox_conversation(self, *, user=None) -> tuple[Task, TaskRun, Conversation]:
        owner = user or self.user
        task = Task.objects.create(
            team=self.team,
            created_by=owner,
            title="Sandbox task",
            description="desc",
            origin_product=Task.OriginProduct.POSTHOG_AI,
        )
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        conversation = Conversation.objects.create(
            user=owner,
            team=self.team,
            task=task,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
        )
        return task, run, conversation

    def _url(self, conversation: Conversation) -> str:
        return f"/api/environments/{self.team.id}/conversations/{conversation.id}/refresh_mcp/"

    def test_refresh_happy_path_returns_200_and_shape(self):
        task, run, conversation = self._sandbox_conversation()

        result = SandboxRefreshMcpResult(
            task_id=str(task.id),
            run_id=str(run.id),
            run_status=TaskRun.Status.IN_PROGRESS,
            refresh_requested=True,
        )
        with patch(ROUTING_PATH, return_value=result) as mock_refresh:
            response = self.client.post(self._url(conversation), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertEqual(body["task_id"], str(task.id))
        self.assertEqual(body["run_id"], str(run.id))
        self.assertEqual(body["run_status"], TaskRun.Status.IN_PROGRESS)
        self.assertTrue(body["refresh_requested"])
        mock_refresh.assert_called_once()

    def test_refresh_emits_telemetry_with_source_only_when_requested(self):
        task, run, conversation = self._sandbox_conversation()
        result = SandboxRefreshMcpResult(
            task_id=str(task.id), run_id=str(run.id), run_status=TaskRun.Status.IN_PROGRESS, refresh_requested=True
        )

        with (
            patch(ROUTING_PATH, return_value=result),
            patch("ee.api.conversation.posthoganalytics.capture") as mock_capture,
        ):
            self.client.post(self._url(conversation), {"source": "mcp_store_install"}, format="json")

        mock_capture.assert_called_once()
        self.assertEqual(mock_capture.call_args.kwargs["event"], "mcp_refresh_requested")
        props = mock_capture.call_args.kwargs["properties"]
        self.assertEqual(props["source"], "mcp_store_install")
        self.assertEqual(props["execution_type"], "sandbox")
        self.assertEqual(props["conversation_id"], str(conversation.id))

    def test_refresh_noop_does_not_emit_telemetry(self):
        task, run, conversation = self._sandbox_conversation()
        result = SandboxRefreshMcpResult(
            task_id=str(task.id), run_id=str(run.id), run_status=TaskRun.Status.COMPLETED, refresh_requested=False
        )

        with (
            patch(ROUTING_PATH, return_value=result),
            patch("ee.api.conversation.posthoganalytics.capture") as mock_capture,
        ):
            response = self.client.post(self._url(conversation), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_capture.assert_not_called()

    def test_refresh_409_when_agent_mid_turn(self):
        _task, _run, conversation = self._sandbox_conversation()

        with patch(ROUTING_PATH, side_effect=SandboxBusyError()):
            response = self.client.post(self._url(conversation), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_refresh_502_when_agent_unreachable(self):
        _task, _run, conversation = self._sandbox_conversation()

        with patch(ROUTING_PATH, side_effect=SandboxCommandError("down")):
            response = self.client.post(self._url(conversation), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)

    def test_refresh_400_when_not_sandbox_runtime(self):
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            agent_runtime=Conversation.AgentRuntime.LANGGRAPH,
        )
        response = self.client.post(self._url(conversation), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_refresh_rejects_invalid_source(self):
        _task, _run, conversation = self._sandbox_conversation()
        response = self.client.post(self._url(conversation), {"source": "not_a_choice"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_refresh_on_other_user_conversation_returns_404(self):
        other_user = self._create_user("other@posthog.com")
        _task, _run, conversation = self._sandbox_conversation(user=other_user)

        response = self.client.post(self._url(conversation), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
