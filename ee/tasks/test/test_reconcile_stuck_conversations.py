import datetime

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from ee.models.assistant import Conversation
from ee.tasks.reconcile_stuck_conversations import reconcile_stuck_conversations


class ReconcileStuckConversationsTest(APIBaseTest):
    def _make_conversation(self, status: Conversation.Status, age: datetime.timedelta) -> Conversation:
        conversation = Conversation.objects.create(user=self.user, team=self.team, status=status)
        # auto_now keeps updated_at fresh on save, so bypass it with a queryset update.
        Conversation.objects.filter(id=conversation.id).update(updated_at=timezone.now() - age)
        return conversation

    def test_resets_stuck_conversation_without_running_workflow(self):
        conversation = self._make_conversation(Conversation.Status.IN_PROGRESS, datetime.timedelta(hours=2))

        with patch(
            "ee.hogai.core.executor.AgentExecutor.has_running_workflow",
            new_callable=AsyncMock,
            return_value=False,
        ):
            reconcile_stuck_conversations()

        conversation.refresh_from_db()
        self.assertEqual(conversation.status, Conversation.Status.IDLE)

    def test_resets_stuck_canceling_conversation(self):
        conversation = self._make_conversation(Conversation.Status.CANCELING, datetime.timedelta(hours=2))

        with patch(
            "ee.hogai.core.executor.AgentExecutor.has_running_workflow",
            new_callable=AsyncMock,
            return_value=False,
        ):
            reconcile_stuck_conversations()

        conversation.refresh_from_db()
        self.assertEqual(conversation.status, Conversation.Status.IDLE)

    def test_leaves_stuck_conversation_with_running_workflow(self):
        conversation = self._make_conversation(Conversation.Status.IN_PROGRESS, datetime.timedelta(hours=2))

        with patch(
            "ee.hogai.core.executor.AgentExecutor.has_running_workflow",
            new_callable=AsyncMock,
            return_value=True,
        ):
            reconcile_stuck_conversations()

        conversation.refresh_from_db()
        self.assertEqual(conversation.status, Conversation.Status.IN_PROGRESS)

    def test_leaves_recent_in_progress_conversation(self):
        conversation = self._make_conversation(Conversation.Status.IN_PROGRESS, datetime.timedelta(minutes=1))

        with patch(
            "ee.hogai.core.executor.AgentExecutor.has_running_workflow",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_has_running_workflow:
            reconcile_stuck_conversations()

        # Too recent to be a candidate, so Temporal is never consulted and status is untouched.
        mock_has_running_workflow.assert_not_called()
        conversation.refresh_from_db()
        self.assertEqual(conversation.status, Conversation.Status.IN_PROGRESS)

    def test_leaves_idle_conversation(self):
        conversation = self._make_conversation(Conversation.Status.IDLE, datetime.timedelta(hours=2))

        with patch(
            "ee.hogai.core.executor.AgentExecutor.has_running_workflow",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_has_running_workflow:
            reconcile_stuck_conversations()

        mock_has_running_workflow.assert_not_called()
        conversation.refresh_from_db()
        self.assertEqual(conversation.status, Conversation.Status.IDLE)
