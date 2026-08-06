# type: ignore

from datetime import timedelta

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.utils import timezone

from products.posthog_ai.backend.models.assistant import Conversation, ConversationCheckpoint

from ee.hogai.django_checkpoint import compaction
from ee.hogai.django_checkpoint.compaction import select_compactable_conversation_ids


class TestCompactionEligibility(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _make_thread(
        self,
        *,
        status: str = Conversation.Status.IDLE,
        idle_days: int = 8,
        root_checkpoints: int = 2,
        subgraph_only: bool = False,
    ) -> Conversation:
        conversation = Conversation.objects.create(user=self.user, team=self.team, status=status)
        ns = "sub" if subgraph_only else ""
        parent = None
        for _ in range(root_checkpoints):
            parent = ConversationCheckpoint.objects.create(
                thread=conversation, checkpoint_ns=ns, parent_checkpoint=parent
            )
        Conversation.objects.filter(pk=conversation.id).update(updated_at=timezone.now() - timedelta(days=idle_days))
        return conversation

    def test_wildcard_allowlist_compacts_any_team(self):
        eligible = self._make_thread()

        with patch.object(compaction, "CHECKPOINT_COMPACTION_MAX_TEAM_ID", "*"):
            assert select_compactable_conversation_ids(limit=100) == [eligible.id]

    def test_selects_only_idle_aged_multi_checkpoint_threads(self):
        eligible = self._make_thread()
        self._make_thread(idle_days=0)  # too recent
        self._make_thread(status=Conversation.Status.IN_PROGRESS)  # mid-run
        self._make_thread(root_checkpoints=1)  # already compacted
        self._make_thread(subgraph_only=True)  # no root chain to compact

        with patch.object(compaction, "CHECKPOINT_COMPACTION_MAX_TEAM_ID", self.team.id):
            selected = select_compactable_conversation_ids(limit=100)

        assert selected == [eligible.id]

    def test_team_allowlist_excludes_teams_above_the_limit(self):
        self._make_thread()

        with patch.object(compaction, "CHECKPOINT_COMPACTION_MAX_TEAM_ID", self.team.id - 1):
            assert select_compactable_conversation_ids(limit=100) == []

    def test_after_id_cursor_paginates(self):
        self._make_thread()
        self._make_thread()

        with patch.object(compaction, "CHECKPOINT_COMPACTION_MAX_TEAM_ID", self.team.id):
            ordered = select_compactable_conversation_ids(limit=100)
            assert len(ordered) == 2

            first_page = select_compactable_conversation_ids(limit=1)
            assert first_page == [ordered[0]]

            second_page = select_compactable_conversation_ids(limit=1, after_id=ordered[0])
            assert second_page == [ordered[1]]
