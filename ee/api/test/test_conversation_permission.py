from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.posthog_ai.backend.models.assistant import Conversation
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.services.agent_command import CommandResult


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
        conversation = Conversation.objects.create(user=self.user, team=self.team, task=run.task)

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
        conversation = Conversation.objects.create(user=self.user, team=self.team, task=run.task)

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

    def test_permission_responded_telemetry_includes_trace_id(self):
        run = self._create_run()
        conversation = Conversation.objects.create(user=self.user, team=self.team, task=run.task)
        trace_id = "123e4567-e89b-12d3-a456-426614174000"

        with (
            patch(
                "ee.api.conversation.send_permission_response",
                return_value=CommandResult(success=True, status_code=200, data={}),
            ),
            patch("ee.api.conversation.posthoganalytics.capture") as mock_capture,
        ):
            self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/permission/",
                {"requestId": "req-3", "optionId": "allow_once", "traceId": trace_id},
                format="json",
            )

        mock_capture.assert_called_once()
        self.assertEqual(mock_capture.call_args.kwargs["event"], "permission_responded")
        props = mock_capture.call_args.kwargs["properties"]
        self.assertEqual(props["trace_id"], trace_id)
        self.assertEqual(props["request_id"], "req-3")
        self.assertEqual(props["option_id"], "allow_once")
        self.assertEqual(props["execution_type"], "sandbox")
        self.assertEqual(props["conversation_id"], str(conversation.id))

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
        conversation = Conversation.objects.create(user=self.user, team=self.team, task=run.task)

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

    def test_permission_targets_originating_run_over_current_run(self):
        run = self._create_run()
        # A successor run on the same task makes `current_run` resolve to the newer run.
        successor = TaskRun.objects.create(task=run.task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        conversation = Conversation.objects.create(user=self.user, team=self.team, task=run.task)

        with patch(
            "ee.api.conversation.send_permission_response",
            return_value=CommandResult(success=True, status_code=200, data={}),
        ) as mock_send:
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/permission/",
                {"requestId": "req-1", "optionId": "allow_once", "runId": str(run.id)},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        args, _ = mock_send.call_args
        # The reply targets the run that emitted the request, not the newer current run.
        self.assertEqual(args[0].id, run.id)
        self.assertNotEqual(args[0].id, successor.id)

    def test_permission_falls_back_to_current_run_without_run_id(self):
        run = self._create_run()
        TaskRun.objects.create(task=run.task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        conversation = Conversation.objects.create(user=self.user, team=self.team, task=run.task)

        with patch(
            "ee.api.conversation.send_permission_response",
            return_value=CommandResult(success=True, status_code=200, data={}),
        ) as mock_send:
            self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/permission/",
                {"requestId": "req-1", "optionId": "allow_once"},
                format="json",
            )

        args, _ = mock_send.call_args
        # No run id supplied → the conversation's current (newest) run.
        self.assertEqual(args[0].id, run.task.latest_run.id)

    def test_permission_responded_telemetry_marks_forward_failure(self):
        run = self._create_run()
        conversation = Conversation.objects.create(user=self.user, team=self.team, task=run.task)

        with (
            patch(
                "ee.api.conversation.send_permission_response",
                return_value=CommandResult(success=False, status_code=502, error="unreachable", retryable=True),
            ),
            patch("ee.api.conversation.posthoganalytics.capture") as mock_capture,
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/conversations/{conversation.id}/permission/",
                {"requestId": "req-1", "optionId": "reject"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        props = mock_capture.call_args.kwargs["properties"]
        # A failed forward must not look like a success in the approval funnel.
        self.assertFalse(props["success"])
        self.assertEqual(props["run_id"], str(run.id))
