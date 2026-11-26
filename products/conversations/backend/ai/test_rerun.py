from datetime import timedelta

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.temporal.ai_reply.activities.build_context import _build_context_sync

RERUN_MODULE = "products.conversations.backend.ai.rerun"
FLAG = "products.conversations.backend.temporal.coordinator._is_master_flag_enabled"


@time_machine.travel("2026-11-26T12:00:00Z", tick=False)
class TestAiRerunAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.team.conversations_settings = {
            "ai_suggestions_enabled": True,
            "ai_reply_modes": {"widget": {"how_to": "bot_reply"}},
        }
        self.team.save()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="ai-rerun-session",
            distinct_id="user-123",
            status=Status.OPEN,
            ai_triage={"status": "done", "result": "suggested"},
        )
        self.comment = Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="My export is broken.",
            item_context={"author_type": "customer", "is_private": False},
        )
        self.url = f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/ai_rerun/"

    def _temporal_client(self, *, start_error: Exception | None = None) -> MagicMock:
        client = MagicMock()
        client.start_workflow = AsyncMock(side_effect=start_error)
        return client

    @patch(FLAG, return_value=True)
    def test_starts_a_manual_run_keyed_on_the_latest_message(self, _flag) -> None:
        # Notes that a run or a teammate wrote later must not change the id, or each run would allow another.
        with time_machine.travel("2026-11-26T12:05:00Z", tick=False):
            for context in ({"author_type": "AI", "is_private": True}, {"author_type": "support", "is_private": True}):
                Comment.objects.create(
                    team=self.team,
                    scope="conversations_ticket",
                    item_id=str(self.ticket.id),
                    content="note",
                    item_context=context,
                )
        client = self._temporal_client()
        with patch(f"{RERUN_MODULE}.sync_connect", return_value=client):
            response = self.client.post(self.url)

        expected_id = f"support-reply-{self.ticket.id}-m{int(self.comment.created_at.timestamp())}"
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json() == {"workflow_id": expected_id}
        _workflow, workflow_input = client.start_workflow.call_args.args
        assert client.start_workflow.call_args.kwargs["id"] == expected_id
        assert workflow_input.trigger == "manual"
        assert workflow_input.ticket_id == str(self.ticket.id)

    @parameterized.expand(
        [
            ("ai_turned_off", {"ai_suggestions_enabled": False}, True, None, None, 400, "ai_rerun_unavailable"),
            ("flag_off", None, False, None, None, 400, "ai_rerun_unavailable"),
            (
                "run_in_progress",
                None,
                True,
                {"status": "in_progress", "started_at": "now"},
                None,
                409,
                "ai_rerun_in_progress",
            ),
            (
                "nothing_new_since_the_last_run",
                None,
                True,
                None,
                WorkflowAlreadyStartedError("support-reply", "support-reply-pipeline"),
                409,
                "ai_rerun_nothing_new",
            ),
        ]
    )
    def test_refuses_with_a_reason(
        self, _name, settings_override, flag_on, triage, start_error, expected_status, expected_error
    ) -> None:
        if settings_override is not None:
            self.team.conversations_settings = settings_override
            self.team.save()
        if triage is not None:
            if triage.get("started_at") == "now":
                triage = {**triage, "started_at": timezone.now().isoformat()}
            self.ticket.ai_triage = triage
            self.ticket.save(update_fields=["ai_triage"])
        client = self._temporal_client(start_error=start_error)

        with patch(FLAG, return_value=flag_on), patch(f"{RERUN_MODULE}.sync_connect", return_value=client):
            response = self.client.post(self.url)

        assert response.status_code == expected_status
        assert response.json()["error_type"] == expected_error
        assert client.start_workflow.await_count == (1 if start_error else 0)
        self.ticket.refresh_from_db()
        assert "manual_run_claimed_at" not in self.ticket.ai_triage

    @patch(FLAG, return_value=True)
    def test_a_second_request_is_refused_while_the_first_is_starting(self, _flag) -> None:
        client = self._temporal_client()
        with patch(f"{RERUN_MODULE}.sync_connect", return_value=client):
            first = self.client.post(self.url)
            second = self.client.post(self.url)

        assert first.status_code == status.HTTP_202_ACCEPTED
        assert second.status_code == status.HTTP_409_CONFLICT
        assert second.json()["error_type"] == "ai_rerun_in_progress"
        assert client.start_workflow.await_count == 1

    @patch(FLAG, return_value=True)
    def test_a_run_stuck_in_progress_does_not_block_forever(self, _flag) -> None:
        self.ticket.ai_triage = {
            "status": "in_progress",
            "started_at": (timezone.now() - timedelta(hours=2)).isoformat(),
        }
        self.ticket.save(update_fields=["ai_triage"])

        with patch(f"{RERUN_MODULE}.sync_connect", return_value=self._temporal_client()):
            response = self.client.post(self.url)

        assert response.status_code == status.HTTP_202_ACCEPTED

    @parameterized.expand([("first_message", ["how_to"]), ("customer_reply", ["how_to"]), ("manual", [])])
    def test_only_a_manual_run_never_auto_publishes(self, trigger, expected_types) -> None:
        with patch("products.conversations.backend.ai.suggest._load_person_properties", return_value={}):
            output = _build_context_sync(self.team.id, str(self.ticket.id), 0, trigger)

        assert output.auto_publish_ticket_types == expected_types
