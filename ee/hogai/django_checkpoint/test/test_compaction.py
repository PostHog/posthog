# type: ignore

import uuid

from posthog.test.base import NonAtomicBaseTest

from asgiref.sync import sync_to_async
from langgraph.checkpoint.base.id import uuid6
from langgraph.checkpoint.serde.types import TASKS
from langgraph.graph import END, START
from langgraph.graph.state import StateGraph
from parameterized import parameterized

from posthog.schema import AssistantMessage, HumanMessage

from products.posthog_ai.backend.models.assistant import (
    Conversation,
    ConversationCheckpoint,
    ConversationCheckpointBlob,
    ConversationCheckpointWrite,
)

from ee.hogai.api.serializers import aget_conversation_state
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.django_checkpoint.compaction import compact_conversation, compact_thread
from ee.hogai.utils.types import AssistantState


@sync_to_async
def _table_counts(thread_id: str) -> dict[str, int]:
    return {
        "checkpoints": ConversationCheckpoint.objects.filter(thread_id=thread_id).count(),
        "blobs": ConversationCheckpointBlob.objects.filter(thread_id=thread_id).count(),
        "writes": ConversationCheckpointWrite.objects.filter(checkpoint__thread_id=thread_id).count(),
    }


@sync_to_async
def _namespace_counts(thread_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ns in ConversationCheckpoint.objects.filter(thread_id=thread_id).values_list("checkpoint_ns", flat=True):
        counts[ns] = counts.get(ns, 0) + 1
    return counts


class TestCheckpointCompaction(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _build_graph(self, checkpointer: DjangoCheckpointer):
        graph = StateGraph(AssistantState)

        def respond(state: AssistantState) -> dict:
            return {"messages": [AssistantMessage(content=f"reply to message {len(state.messages)}")]}

        graph.add_node("respond", respond)
        graph.add_edge(START, "respond")
        graph.add_edge("respond", END)
        return graph.compile(checkpointer=checkpointer)

    async def _seed_conversation(self, n_turns: int) -> tuple[Conversation, object, dict]:
        conversation = await Conversation.objects.acreate(user=self.user, team=self.team)
        graph = self._build_graph(DjangoCheckpointer())
        config = {"configurable": {"thread_id": str(conversation.id), "checkpoint_ns": ""}}
        for turn in range(n_turns):
            await graph.ainvoke({"messages": [HumanMessage(content=f"question {turn}")]}, config)
        return conversation, graph, config

    def _build_nested_graph(self, checkpointer: DjangoCheckpointer):
        subgraph = StateGraph(AssistantState)

        def sub_first(state: AssistantState) -> dict:
            return {"messages": [AssistantMessage(content="sub first")]}

        def sub_second(state: AssistantState) -> dict:
            return {"messages": [AssistantMessage(content="sub second")]}

        subgraph.add_node("sub_first", sub_first)
        subgraph.add_node("sub_second", sub_second)
        subgraph.add_edge(START, "sub_first")
        subgraph.add_edge("sub_first", "sub_second")
        subgraph.add_edge("sub_second", END)

        parent = StateGraph(AssistantState)
        parent.add_node("child", subgraph.compile())
        parent.add_edge(START, "child")
        parent.add_edge("child", END)
        return parent.compile(checkpointer=checkpointer)

    async def _message_contents(self, conversation: Conversation) -> list[str]:
        state, _, _ = await aget_conversation_state(conversation, self.team, self.user)
        assert state is not None, "UI load path returned no state"
        return [m.content for m in state.messages]

    async def test_compaction_handles_nested_subgraphs(self):
        conversation = await Conversation.objects.acreate(user=self.user, team=self.team)
        graph = self._build_nested_graph(DjangoCheckpointer())
        config = {"configurable": {"thread_id": str(conversation.id), "checkpoint_ns": ""}}
        for turn in range(2):
            await graph.ainvoke({"messages": [HumanMessage(content=f"question {turn}")]}, config)

        before = await _namespace_counts(str(conversation.id))
        subgraph_namespaces = [ns for ns in before if ns != ""]
        assert subgraph_namespaces, "expected subgraph checkpoints under a non-root namespace"
        assert all(before[ns] > 1 for ns in subgraph_namespaces), "subgraph namespaces should accumulate checkpoints"
        messages_before = await self._message_contents(conversation)

        # Root-only compaction (the old admin behaviour) leaves every subgraph namespace untouched.
        await sync_to_async(compact_thread)(str(conversation.id))
        after_root_only = await _namespace_counts(str(conversation.id))
        assert {ns: after_root_only[ns] for ns in subgraph_namespaces} == {ns: before[ns] for ns in subgraph_namespaces}

        # compact_conversation collapses every namespace to its tip.
        result = await sync_to_async(compact_conversation)(str(conversation.id))
        assert result.compacted is True
        after = await _namespace_counts(str(conversation.id))
        assert all(count == 1 for count in after.values()), f"every namespace must collapse to its tip: {after}"

        # The whole conversation — including subgraph state — still loads and resumes unchanged.
        assert await self._message_contents(conversation) == messages_before
        await graph.ainvoke({"messages": [HumanMessage(content="after compaction")]}, config)
        resumed = await self._message_contents(conversation)
        assert resumed[: len(messages_before)] == messages_before
        assert "after compaction" in resumed

    @parameterized.expand([("two_turns", 2), ("four_turns", 4)])
    async def test_compaction_keeps_conversation_loadable_and_resumable(self, _name: str, n_turns: int):
        conversation, graph, config = await self._seed_conversation(n_turns)

        before = await _table_counts(str(conversation.id))
        assert before["checkpoints"] > 1, "expected multiple checkpoints before compaction"

        messages_before = await self._message_contents(conversation)
        assert len(messages_before) == 2 * n_turns

        result = await sync_to_async(compact_thread)(str(conversation.id))
        assert result.compacted is True
        assert result.checkpoints_deleted > 0
        assert result.blobs_deleted > 0

        after = await _table_counts(str(conversation.id))
        assert after["checkpoints"] == 1, "compaction must leave exactly one checkpoint"
        assert after["blobs"] < before["blobs"], "compaction must reclaim superseded blobs"
        assert after["writes"] < before["writes"], "compaction must reclaim superseded writes"

        # The UI load path still returns the full transcript, unchanged.
        messages_after = await self._message_contents(conversation)
        assert messages_after == messages_before

        # And the thread is still resumable: a further turn sees the prior context.
        await graph.ainvoke({"messages": [HumanMessage(content="after compaction")]}, config)
        messages_resumed = await self._message_contents(conversation)
        assert messages_resumed[: len(messages_before)] == messages_before
        assert "after compaction" in messages_resumed
        assert len(messages_resumed) == 2 * n_turns + 2

    async def test_compaction_is_idempotent(self):
        conversation, _, _ = await self._seed_conversation(3)

        first = await sync_to_async(compact_thread)(str(conversation.id))
        assert first.compacted is True

        second = await sync_to_async(compact_thread)(str(conversation.id))
        assert second.compacted is False
        assert second.checkpoints_deleted == 0

        after = await _table_counts(str(conversation.id))
        assert after["checkpoints"] == 1
        assert await self._message_contents(conversation) == [
            "question 0",
            "reply to message 1",
            "question 1",
            "reply to message 3",
            "question 2",
            "reply to message 5",
        ]

    async def test_compaction_ignores_higher_id_null_checkpoint_placeholder(self):
        conversation, _, _ = await self._seed_conversation(2)
        messages_before = await self._message_contents(conversation)
        real_tip = (
            await ConversationCheckpoint.objects.filter(thread_id=conversation.id, checkpoint__isnull=False)
            .order_by("-id")
            .afirst()
        )

        # A `put_writes` placeholder: higher id than the real tip, but no checkpoint JSON yet.
        placeholder = await ConversationCheckpoint.objects.acreate(
            id=str(uuid6()),
            thread=conversation,
            checkpoint_ns="",
            parent_checkpoint=real_tip,
            checkpoint=None,
        )
        assert str(placeholder.id) > str(real_tip.id), "placeholder must sort above the real tip to exercise the bug"

        result = await sync_to_async(compact_thread)(str(conversation.id))
        assert result.compacted is True

        # The real state survives and still loads; the null placeholder was never treated as the tip.
        assert await self._message_contents(conversation) == messages_before
        surviving_real = await ConversationCheckpoint.objects.filter(
            thread_id=conversation.id, checkpoint__isnull=False
        ).acount()
        assert surviving_real == 1

    async def test_compaction_skips_tip_with_pending_sends(self):
        conversation, _, _ = await self._seed_conversation(2)
        tip = (
            await ConversationCheckpoint.objects.filter(thread_id=conversation.id, checkpoint__isnull=False)
            .order_by("-id")
            .afirst()
        )
        assert tip.parent_checkpoint_id is not None
        await ConversationCheckpointWrite.objects.acreate(
            checkpoint_id=tip.parent_checkpoint_id,
            task_id=uuid.uuid4(),
            idx=0,
            channel=TASKS,
            type="msgpack",
            blob=b"",
        )

        before = await _table_counts(str(conversation.id))
        result = await sync_to_async(compact_thread)(str(conversation.id))

        assert result.compacted is False
        after = await _table_counts(str(conversation.id))
        assert after["checkpoints"] == before["checkpoints"], "tip with pending sends must be untouched"

    @parameterized.expand(
        [
            ("in_progress", {"status": Conversation.Status.IN_PROGRESS}),
            ("canceling", {"status": Conversation.Status.CANCELING}),
            ("pending_approval", {"approval_decisions": {"p1": {"decision_status": "pending"}}}),
        ]
    )
    async def test_compaction_skips_unsafe_conversations(self, _name: str, unsafe_fields: dict):
        conversation, _, _ = await self._seed_conversation(3)
        await Conversation.objects.filter(pk=conversation.id).aupdate(**unsafe_fields)

        before = await _table_counts(str(conversation.id))
        result = await sync_to_async(compact_thread)(str(conversation.id))

        assert result.compacted is False
        after = await _table_counts(str(conversation.id))
        assert after["checkpoints"] == before["checkpoints"], "unsafe conversation must be untouched"
