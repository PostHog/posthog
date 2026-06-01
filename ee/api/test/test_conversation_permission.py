from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.services.agent_command import CommandResult

from ee.models.assistant import Conversation


class TestConversationPermission(APIBaseTest):
    def _create_run(self) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Sandbox task",
            description="desc",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        return TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

    def test_permission_delegates_with_permission_response_method(self):
        run = self._create_run()
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, sandbox_task_id=run.task.id, sandbox_run_id=run.id
        )

        with patch(
            "ee.api.conversation.send_permission_response",
            return_value=CommandResult(success=True, status_code=200, data={}),
        ) as mock_send:
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/permission/",
                {"requestId": "req-1", "optionId": "allow_once"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["status"], "ok")
        mock_send.assert_called_once()
        _, kwargs = mock_send.call_args
        self.assertEqual(kwargs["request_id"], "req-1")
        self.assertEqual(kwargs["option_id"], "allow_once")

    def test_permission_forwards_custom_input(self):
        run = self._create_run()
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, sandbox_task_id=run.task.id, sandbox_run_id=run.id
        )

        with patch(
            "ee.api.conversation.send_permission_response",
            return_value=CommandResult(success=True, status_code=200, data={}),
        ) as mock_send:
            self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/permission/",
                {"requestId": "req-2", "optionId": "reject_with_feedback", "customInput": "try harder"},
                format="json",
            )

        _, kwargs = mock_send.call_args
        self.assertEqual(kwargs["custom_input"], "try harder")

    def test_permission_400_when_no_sandbox_run(self):
        conversation = Conversation.objects.create(user=self.user, team=self.team)
        response = self.client.post(
            f"/api/environments/{self.team.id}/conversations/{conversation.id}/permission/",
            {"requestId": "req-1", "optionId": "allow_once"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_permission_502_when_agent_unreachable(self):
        run = self._create_run()
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, sandbox_task_id=run.task.id, sandbox_run_id=run.id
        )

        with patch(
            "ee.api.conversation.send_permission_response",
            return_value=CommandResult(success=False, status_code=502, error="unreachable", retryable=True),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/permission/",
                {"requestId": "req-1", "optionId": "reject"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
