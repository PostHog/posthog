from datetime import timedelta

import pytest
from unittest.mock import patch

from django.utils import timezone

from asgiref.sync import sync_to_async

from posthog.temporal.ai.checkpoint_compaction.activities import (
    compact_checkpoint_conversations,
    select_checkpoint_compaction_batch,
)
from posthog.temporal.ai.checkpoint_compaction.types import CompactionBatch, SelectBatchInput

from products.posthog_ai.backend.models.assistant import Conversation, ConversationCheckpoint

from ee.hogai.django_checkpoint import compaction

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


def _seed_compactable(team, user) -> Conversation:
    conversation = Conversation.objects.create(team=team, user=user)
    parent = None
    for _ in range(3):
        parent = ConversationCheckpoint.objects.create(
            thread=conversation,
            checkpoint_ns="",
            parent_checkpoint=parent,
            checkpoint={"channel_versions": {}},
        )
    Conversation.objects.filter(pk=conversation.id).update(updated_at=timezone.now() - timedelta(days=8))
    return conversation


async def test_select_then_compact_activities_end_to_end(ateam, auser, activity_environment):
    conversation = await sync_to_async(_seed_compactable)(ateam, auser)

    with patch.object(compaction, "CHECKPOINT_COMPACTION_MAX_TEAM_ID", ateam.id):
        batch = await activity_environment.run(select_checkpoint_compaction_batch, SelectBatchInput(batch_size=10))
        assert batch.conversation_ids == [str(conversation.id)]

        result = await activity_environment.run(
            compact_checkpoint_conversations, CompactionBatch(conversation_ids=batch.conversation_ids)
        )

    assert result.conversations_compacted == 1
    assert result.checkpoints_deleted == 2

    remaining = await sync_to_async(ConversationCheckpoint.objects.filter(thread_id=conversation.id).count)()
    assert remaining == 1


async def test_one_poison_thread_does_not_sink_the_batch(ateam, auser, activity_environment):
    healthy = await sync_to_async(_seed_compactable)(ateam, auser)
    poison = await sync_to_async(_seed_compactable)(ateam, auser)

    real_compact_thread = compaction.compact_thread

    def flaky_compact_thread(thread_id, *args, **kwargs):
        if thread_id == str(poison.id):
            raise RuntimeError("boom")
        return real_compact_thread(thread_id, *args, **kwargs)

    with (
        patch.object(compaction, "CHECKPOINT_COMPACTION_MAX_TEAM_ID", ateam.id),
        patch(
            "posthog.temporal.ai.checkpoint_compaction.activities.compact_thread",
            side_effect=flaky_compact_thread,
        ),
    ):
        result = await activity_environment.run(
            compact_checkpoint_conversations,
            CompactionBatch(conversation_ids=[str(poison.id), str(healthy.id)]),
        )

    # The poison thread is counted and skipped; the healthy thread that follows it still compacts.
    assert result.conversations_failed == 1
    assert result.conversations_compacted == 1
    assert await sync_to_async(ConversationCheckpoint.objects.filter(thread_id=healthy.id).count)() == 1
    assert await sync_to_async(ConversationCheckpoint.objects.filter(thread_id=poison.id).count)() == 3
