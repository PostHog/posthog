# type: ignore

from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    Checkpoint,
    CheckpointMetadata,
    create_checkpoint,
    empty_checkpoint,
)
from langgraph.checkpoint.base.id import uuid6
from langgraph.errors import NodeInterrupt
from langgraph.graph import END, START
from langgraph.graph.state import CompiledStateGraph, StateGraph

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.models.assistant import (
    Conversation,
    ConversationCheckpoint,
    ConversationCheckpointBlob,
    ConversationCheckpointWrite,
)
from posthog.test.base import NonAtomicBaseTest


class TestDjangoCheckpointer(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _build_graph(self, checkpointer: DjangoCheckpointer):
        class State(TypedDict):
            val: int

        graph = StateGraph(State)

        def handle_node1(state: State) -> State:
            if state["val"] == 1:
                raise NodeInterrupt("test")
            return {"val": state["val"] + 1}

        graph.add_node("node1", handle_node1)
        graph.add_node("node2", lambda state: state)

        graph.add_edge(START, "node1")
        graph.add_edge("node1", "node2")
        graph.add_edge("node2", END)

        return graph.compile(checkpointer=checkpointer)

    def test_saver(self):
        thread1 = Conversation.objects.create(user=self.user, team=self.team)
        thread2 = Conversation.objects.create(user=self.user, team=self.team)

        config_1: RunnableConfig = {
            "configurable": {
                "thread_id": thread1.id,
                "checkpoint_ns": "",
            }
        }
        chkpnt_1: Checkpoint = empty_checkpoint()

        config_2: RunnableConfig = {
            "configurable": {
                "thread_id": thread2.id,
                "checkpoint_ns": "",
            }
        }
        chkpnt_2: Checkpoint = create_checkpoint(chkpnt_1, {}, 1)

        config_3: RunnableConfig = {
            "configurable": {
                "thread_id": thread2.id,
                "checkpoint_id": chkpnt_2["id"],
                "checkpoint_ns": "inner",
            }
        }
        chkpnt_3: Checkpoint = empty_checkpoint()

        metadata_1: CheckpointMetadata = {
            "source": "input",
            "step": 2,
            "writes": {},
            "score": 1,
        }
        metadata_2: CheckpointMetadata = {
            "source": "loop",
            "step": 1,
            "writes": {"foo": "bar"},
            "score": None,
        }
        metadata_3: CheckpointMetadata = {}

        test_data = {
            "configs": [config_1, config_2, config_3],
            "checkpoints": [chkpnt_1, chkpnt_2, chkpnt_3],
            "metadata": [metadata_1, metadata_2, metadata_3],
        }

        saver = DjangoCheckpointer()

        configs = test_data["configs"]
        checkpoints = test_data["checkpoints"]
        metadata = test_data["metadata"]

        saver.put(configs[0], checkpoints[0], metadata[0], {})
        saver.put(configs[1], checkpoints[1], metadata[1], {})
        saver.put(configs[2], checkpoints[2], metadata[2], {})

        # call method / assertions
        query_1 = {"source": "input"}  # search by 1 key
        query_2 = {
            "step": 1,
            "writes": {"foo": "bar"},
        }  # search by multiple keys
        query_3: dict[str, Any] = {}  # search by no keys, return all checkpoints
        query_4 = {"source": "update", "step": 1}  # no match

        search_results_1 = list(saver.list(None, filter=query_1))
        assert len(search_results_1) == 1
        assert search_results_1[0].metadata == metadata[0]

        search_results_2 = list(saver.list(None, filter=query_2))
        assert len(search_results_2) == 1
        assert search_results_2[0].metadata == metadata[1]

        search_results_3 = list(saver.list(None, filter=query_3))
        assert len(search_results_3) == 3

        search_results_4 = list(saver.list(None, filter=query_4))
        assert len(search_results_4) == 0

        # search by config (defaults to checkpoints across all namespaces)
        search_results_5 = list(saver.list({"configurable": {"thread_id": thread2.id}}))
        assert len(search_results_5) == 2
        assert {
            search_results_5[0].config["configurable"]["checkpoint_ns"],
            search_results_5[1].config["configurable"]["checkpoint_ns"],
        } == {"", "inner"}

    def test_channel_versions(self):
        thread1 = Conversation.objects.create(user=self.user, team=self.team)

        chkpnt = {
            "v": 1,
            "ts": "2024-07-31T20:14:19.804150+00:00",
            "id": str(uuid6(clock_seq=-2)),
            "channel_values": {
                "post": "hog",
                "node": "node",
            },
            "channel_versions": {
                "__start__": 2,
                "my_key": 3,
                "start:node": 3,
                "node": 3,
            },
            "versions_seen": {
                "__input__": {},
                "__start__": {"__start__": 1},
                "node": {"start:node": 2},
            },
            "pending_sends": [],
        }
        metadata = {"meta": "key"}

        write_config = {"configurable": {"thread_id": thread1.id, "checkpoint_ns": ""}}
        read_config = {"configurable": {"thread_id": thread1.id}}

        saver = DjangoCheckpointer()
        saver.put(write_config, chkpnt, metadata, {})

        checkpoint = ConversationCheckpoint.objects.first()
        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint.thread, thread1)
        self.assertEqual(checkpoint.checkpoint_ns, "")
        self.assertEqual(str(checkpoint.id), chkpnt["id"])
        self.assertIsNone(checkpoint.parent_checkpoint)
        chkpnt.pop("channel_values")
        self.assertEqual(checkpoint.checkpoint, chkpnt)
        self.assertEqual(checkpoint.metadata, metadata)

        checkpoints = list(saver.list(read_config))
        self.assertEqual(len(checkpoints), 1)

        checkpoint = saver.get(read_config)
        self.assertEqual(checkpoint, checkpoints[0].checkpoint)

    def test_put_copies_checkpoint(self):
        thread1 = Conversation.objects.create(user=self.user, team=self.team)
        chkpnt = {
            "v": 1,
            "ts": "2024-07-31T20:14:19.804150+00:00",
            "id": str(uuid6(clock_seq=-2)),
            "channel_values": {
                "post": "hog",
                "node": "node",
            },
            "channel_versions": {
                "__start__": 2,
                "my_key": 3,
                "start:node": 3,
                "node": 3,
            },
            "versions_seen": {
                "__input__": {},
                "__start__": {"__start__": 1},
                "node": {"start:node": 2},
            },
            "pending_sends": [],
        }
        metadata = {"meta": "key"}
        write_config = {"configurable": {"thread_id": thread1.id, "checkpoint_ns": ""}}
        saver = DjangoCheckpointer()
        saver.put(write_config, chkpnt, metadata, {})
        self.assertIn("channel_values", chkpnt)

    def test_concurrent_puts_and_put_writes(self):
        graph: CompiledStateGraph = self._build_graph(DjangoCheckpointer())
        thread = Conversation.objects.create(user=self.user, team=self.team)
        config = {"configurable": {"thread_id": str(thread.id)}}
        graph.invoke(
            {"val": 0},
            config=config,
        )
        self.assertEqual(len(ConversationCheckpoint.objects.all()), 4)
        self.assertEqual(len(ConversationCheckpointBlob.objects.all()), 10)
        self.assertEqual(len(ConversationCheckpointWrite.objects.all()), 6)

    def test_resuming(self):
        checkpointer = DjangoCheckpointer()
        graph: CompiledStateGraph = self._build_graph(checkpointer)
        thread = Conversation.objects.create(user=self.user, team=self.team)
        config = {"configurable": {"thread_id": str(thread.id)}}

        graph.invoke(
            {"val": 1},
            config=config,
        )
        snapshot = graph.get_state(config)
        self.assertIsNotNone(snapshot.next)
        self.assertEqual(snapshot.tasks[0].interrupts[0].value, "test")

        self.assertEqual(len(ConversationCheckpoint.objects.all()), 2)
        self.assertEqual(len(ConversationCheckpointBlob.objects.all()), 4)
        self.assertEqual(len(ConversationCheckpointWrite.objects.all()), 3)
        self.assertEqual(len(list(checkpointer.list(config))), 2)

        latest_checkpoint = ConversationCheckpoint.objects.last()
        latest_write = ConversationCheckpointWrite.objects.filter(checkpoint=latest_checkpoint).first()
        actual_checkpoint = checkpointer.get_tuple(config)
        self.assertIsNotNone(actual_checkpoint)
        self.assertIsNotNone(latest_write)
        self.assertEqual(len(latest_checkpoint.writes.all()), 1)
        blobs = list(latest_checkpoint.blobs.all())
        self.assertEqual(len(blobs), 3)
        self.assertEqual(actual_checkpoint.checkpoint["id"], str(latest_checkpoint.id))
        self.assertEqual(len(actual_checkpoint.pending_writes), 1)
        self.assertEqual(actual_checkpoint.pending_writes[0][0], str(latest_write.task_id))

        graph.update_state(config, {"val": 2})
        # add the value update checkpoint
        self.assertEqual(len(ConversationCheckpoint.objects.all()), 3)
        self.assertEqual(len(ConversationCheckpointBlob.objects.all()), 6)
        self.assertEqual(len(ConversationCheckpointWrite.objects.all()), 5)
        self.assertEqual(len(list(checkpointer.list(config))), 3)

        res = graph.invoke(None, config=config)
        self.assertEqual(len(ConversationCheckpoint.objects.all()), 5)
        self.assertEqual(len(ConversationCheckpointBlob.objects.all()), 12)
        self.assertEqual(len(ConversationCheckpointWrite.objects.all()), 9)
        self.assertEqual(len(list(checkpointer.list(config))), 5)
        self.assertEqual(res, {"val": 3})
        snapshot = graph.get_state(config)
        self.assertFalse(snapshot.next)
