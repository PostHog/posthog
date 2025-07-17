# type: ignore

import asyncio
import operator
from typing import Annotated, Any, Optional, TypedDict
from uuid import uuid4

from asgiref.sync import async_to_sync
from django.db import connection
from django.test.utils import CaptureQueriesContext
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
from pydantic import BaseModel, Field

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

    async def test_saver(self):
        """Test the basic save and search functionality of the checkpointer."""
        thread1 = await Conversation.objects.acreate(user=self.user, team=self.team)
        thread2 = await Conversation.objects.acreate(user=self.user, team=self.team)

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

        await saver.aput(configs[0], checkpoints[0], metadata[0], {})
        await saver.aput(configs[1], checkpoints[1], metadata[1], {})
        await saver.aput(configs[2], checkpoints[2], metadata[2], {})

        # call method / assertions
        query_1 = {"source": "input"}  # search by 1 key
        query_2 = {
            "step": 1,
            "writes": {"foo": "bar"},
        }  # search by multiple keys
        query_3: dict[str, Any] = {}  # search by no keys, return all checkpoints
        query_4 = {"source": "update", "step": 1}  # no match

        search_results_1 = [result async for result in saver.alist(None, filter=query_1)]
        assert len(search_results_1) == 1
        assert search_results_1[0].metadata == metadata[0]

        search_results_2 = [result async for result in saver.alist(None, filter=query_2)]
        assert len(search_results_2) == 1
        assert search_results_2[0].metadata == metadata[1]

        search_results_3 = [result async for result in saver.alist(None, filter=query_3)]
        assert len(search_results_3) == 3

        search_results_4 = [result async for result in saver.alist(None, filter=query_4)]
        assert len(search_results_4) == 0

        # search by config (defaults to checkpoints across all namespaces)
        search_results_5 = [result async for result in saver.alist({"configurable": {"thread_id": thread2.id}})]
        assert len(search_results_5) == 2
        assert {
            search_results_5[0].config["configurable"]["checkpoint_ns"],
            search_results_5[1].config["configurable"]["checkpoint_ns"],
        } == {"", "inner"}

    async def test_channel_versions(self):
        """Test that channel versions are properly saved and loaded."""
        thread1 = await Conversation.objects.acreate(user=self.user, team=self.team)

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
        await saver.aput(write_config, chkpnt, metadata, {})

        checkpoint = await ConversationCheckpoint.objects.select_related("thread", "parent_checkpoint").afirst()
        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint.thread, thread1)
        self.assertEqual(checkpoint.checkpoint_ns, "")
        self.assertEqual(str(checkpoint.id), chkpnt["id"])
        self.assertIsNone(checkpoint.parent_checkpoint)
        chkpnt.pop("channel_values")
        self.assertEqual(checkpoint.checkpoint, chkpnt)
        self.assertEqual(checkpoint.metadata, metadata)

        checkpoints = [result async for result in saver.alist(read_config)]
        self.assertEqual(len(checkpoints), 1)

        checkpoint_tuple = await saver.aget_tuple(read_config)
        self.assertEqual(checkpoint_tuple.checkpoint, checkpoints[0].checkpoint)

    async def test_put_copies_checkpoint(self):
        """Test that put operations properly copy checkpoint data."""
        thread1 = await Conversation.objects.acreate(user=self.user, team=self.team)
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
        await saver.aput(write_config, chkpnt, metadata, {})
        self.assertIn("channel_values", chkpnt)

    async def test_concurrent_puts_and_put_writes(self):
        """Test concurrent checkpoint operations and write operations."""
        graph: CompiledStateGraph = self._build_graph(DjangoCheckpointer())
        thread = await Conversation.objects.acreate(user=self.user, team=self.team)
        config = {"configurable": {"thread_id": str(thread.id)}}
        await graph.ainvoke(
            {"val": 0},
            config=config,
        )
        self.assertEqual(await ConversationCheckpoint.objects.acount(), 4)
        self.assertEqual(await ConversationCheckpointBlob.objects.acount(), 9)
        self.assertEqual(await ConversationCheckpointWrite.objects.acount(), 5)

    async def test_resuming(self):
        """Test resuming execution from a checkpoint after an interrupt."""
        checkpointer = DjangoCheckpointer()
        graph: CompiledStateGraph = self._build_graph(checkpointer)
        thread = await Conversation.objects.acreate(user=self.user, team=self.team)
        config = {"configurable": {"thread_id": str(thread.id)}}

        await graph.ainvoke(
            {"val": 1},
            config=config,
        )
        snapshot = await graph.aget_state(config)
        self.assertIsNotNone(snapshot.next)
        self.assertEqual(snapshot.tasks[0].interrupts[0].value, "test")

        self.assertEqual(await ConversationCheckpoint.objects.acount(), 2)
        self.assertEqual(await ConversationCheckpointBlob.objects.acount(), 4)
        self.assertEqual(await ConversationCheckpointWrite.objects.acount(), 3)
        checkpoints_list = [result async for result in checkpointer.alist(config)]
        self.assertEqual(len(checkpoints_list), 2)

        latest_checkpoint = await ConversationCheckpoint.objects.alast()
        latest_write = await ConversationCheckpointWrite.objects.filter(checkpoint=latest_checkpoint).afirst()
        actual_checkpoint = await checkpointer.aget_tuple(config)
        self.assertIsNotNone(actual_checkpoint)
        self.assertIsNotNone(latest_write)
        self.assertEqual(await latest_checkpoint.writes.acount(), 1)
        blobs = [blob async for blob in latest_checkpoint.blobs.all()]
        self.assertEqual(len(blobs), 3)
        self.assertEqual(actual_checkpoint.checkpoint["id"], str(latest_checkpoint.id))
        self.assertEqual(len(actual_checkpoint.pending_writes), 1)
        self.assertEqual(actual_checkpoint.pending_writes[0][0], str(latest_write.task_id))

        await graph.aupdate_state(config, {"val": 2})
        # add the value update checkpoint
        self.assertEqual(await ConversationCheckpoint.objects.acount(), 3)
        self.assertEqual(await ConversationCheckpointBlob.objects.acount(), 6)
        self.assertEqual(await ConversationCheckpointWrite.objects.acount(), 5)
        checkpoints_list = [result async for result in checkpointer.alist(config)]
        self.assertEqual(len(checkpoints_list), 3)

        res = await graph.ainvoke(None, config=config)
        self.assertEqual(await ConversationCheckpoint.objects.acount(), 5)
        self.assertEqual(await ConversationCheckpointBlob.objects.acount(), 11)
        self.assertEqual(await ConversationCheckpointWrite.objects.acount(), 8)
        checkpoints_list = [result async for result in checkpointer.alist(config)]
        self.assertEqual(len(checkpoints_list), 5)
        self.assertEqual(res, {"val": 3})
        snapshot = await graph.aget_state(config)
        self.assertFalse(snapshot.next)

    async def test_checkpoint_blobs_are_bound_to_thread(self):
        """Test that checkpoint blobs are properly bound to their thread."""

        class State(TypedDict, total=False):
            messages: Annotated[list[str], operator.add]
            string: Optional[str]

        graph = StateGraph(State)

        def handle_node1(state: State):
            return

        def handle_node2(state: State):
            raise NodeInterrupt("test")

        graph.add_node("node1", handle_node1)
        graph.add_node("node2", handle_node2)

        graph.add_edge(START, "node1")
        graph.add_edge("node1", "node2")
        graph.add_edge("node2", END)

        compiled = graph.compile(checkpointer=DjangoCheckpointer())

        thread = await Conversation.objects.acreate(user=self.user, team=self.team)
        config = {"configurable": {"thread_id": str(thread.id)}}
        await compiled.ainvoke({"messages": ["hello"], "string": "world"}, config=config)

        snapshot = await compiled.aget_state(config)
        self.assertIsNotNone(snapshot.next)
        self.assertEqual(snapshot.tasks[0].interrupts[0].value, "test")
        saved_state = snapshot.values
        self.assertEqual(saved_state["messages"], ["hello"])
        self.assertEqual(saved_state["string"], "world")

    async def test_checkpoint_can_save_and_load_pydantic_state(self):
        """Test that checkpoints can save and load Pydantic model state."""

        class State(BaseModel):
            messages: Annotated[list[str], operator.add]
            string: Optional[str]

        class PartialState(BaseModel):
            messages: Optional[list[str]] = Field(default=None)
            string: Optional[str] = Field(default=None)

        graph = StateGraph(State)

        def handle_node1(state: State):
            return PartialState()

        def handle_node2(state: State):
            raise NodeInterrupt("test")

        graph.add_node("node1", handle_node1)
        graph.add_node("node2", handle_node2)

        graph.add_edge(START, "node1")
        graph.add_edge("node1", "node2")
        graph.add_edge("node2", END)

        compiled = graph.compile(checkpointer=DjangoCheckpointer())

        thread = await Conversation.objects.acreate(user=self.user, team=self.team)
        config = {"configurable": {"thread_id": str(thread.id)}}
        await compiled.ainvoke({"messages": ["hello"], "string": "world"}, config=config)

        snapshot = await compiled.aget_state(config)
        self.assertIsNotNone(snapshot.next)
        self.assertEqual(snapshot.tasks[0].interrupts[0].value, "test")
        saved_state = snapshot.values
        self.assertEqual(saved_state["messages"], ["hello"])
        self.assertEqual(saved_state["string"], "world")

    async def test_saved_blobs(self):
        """Test that blobs are properly saved during checkpoint operations."""

        class State(TypedDict, total=False):
            messages: Annotated[list[str], operator.add]

        graph = StateGraph(State)

        def handle_node1(state: State):
            return {"messages": ["world"]}

        graph.add_node("node1", handle_node1)

        graph.add_edge(START, "node1")
        graph.add_edge("node1", END)

        checkpointer = DjangoCheckpointer()
        compiled = graph.compile(checkpointer=checkpointer)

        thread = await Conversation.objects.acreate(user=self.user, team=self.team)
        config = {"configurable": {"thread_id": str(thread.id)}}
        await compiled.ainvoke({"messages": ["hello"]}, config=config)

        snapshot = await compiled.aget_state(config)
        self.assertFalse(snapshot.next)
        saved_state = snapshot.values
        self.assertEqual(saved_state["messages"], ["hello", "world"])

        blobs = [blob async for blob in ConversationCheckpointBlob.objects.filter(thread=thread)]
        self.assertEqual(len(blobs), 6)

        # Set initial state
        self.assertEqual(blobs[0].channel, "__start__")
        self.assertEqual(blobs[0].type, "msgpack")
        self.assertEqual(
            checkpointer.serde.loads_typed((blobs[0].type, blobs[0].blob)),
            {"messages": ["hello"]},
        )

        # Set first node
        self.assertEqual(blobs[1].channel, "__start__")
        self.assertEqual(blobs[1].type, "empty")
        self.assertIsNone(blobs[1].blob)

        # Set value channels before start
        self.assertEqual(blobs[2].channel, "messages")
        self.assertEqual(blobs[2].type, "msgpack")
        self.assertEqual(
            checkpointer.serde.loads_typed((blobs[2].type, blobs[2].blob)),
            ["hello"],
        )

        # Transition to node1
        self.assertEqual(blobs[3].channel, "branch:to:node1")
        self.assertEqual(blobs[3].type, "null")
        self.assertEqual(
            checkpointer.serde.loads_typed((blobs[3].type, blobs[3].blob)),
            None,
        )

        # Set new state for messages
        self.assertEqual(blobs[4].channel, "messages")
        self.assertEqual(blobs[4].type, "msgpack")
        self.assertEqual(
            checkpointer.serde.loads_typed((blobs[4].type, blobs[4].blob)),
            ["hello", "world"],
        )

        # After setting a state
        self.assertEqual(blobs[5].channel, "branch:to:node1")
        self.assertEqual(blobs[5].type, "empty")
        self.assertIsNone(blobs[5].blob)

    def test_alist_query_efficiency(self):
        """Test that alist doesn't cause N+1 queries when fetching pending writes."""
        thread = Conversation.objects.create(user=self.user, team=self.team)
        saver = DjangoCheckpointer()

        checkpoints = []
        configs = []

        for i in range(5):
            config: RunnableConfig = {
                "configurable": {
                    "thread_id": str(thread.id),
                    "checkpoint_ns": "",
                }
            }

            if i == 0:
                checkpoint = empty_checkpoint()
            else:
                # Create checkpoints that have parent relationships
                parent_checkpoint = checkpoints[i - 1]
                checkpoint = create_checkpoint(parent_checkpoint, {}, i)

            metadata: CheckpointMetadata = {
                "source": "test",
                "step": i,
                "writes": {"test": f"value_{i}"},
            }

            # Save the checkpoint
            saved_config = async_to_sync(saver.aput)(config, checkpoint, metadata, {})
            configs.append(saved_config)
            checkpoints.append(checkpoint)

            # Add some writes to the checkpoint
            writes = [
                (f"channel_{i}_1", f"value_{i}_1"),
                (f"channel_{i}_2", f"value_{i}_2"),
            ]
            async_to_sync(saver.aput_writes)(saved_config, writes, str(uuid4()))

        # Count queries while listing checkpoints
        config = {"configurable": {"thread_id": str(thread.id)}}

        with CaptureQueriesContext(connection) as context:

            @async_to_sync
            async def call_list():
                [result async for result in saver.alist(config)]

            call_list()

            self.assertEqual(len(context.captured_queries), 7)

    async def test_thread_put_and_put_writes_race_condition(self):
        """Test race condition with threads calling put and put_writes for same checkpoint."""

        thread = await Conversation.objects.acreate(user=self.user, team=self.team)
        saver = DjangoCheckpointer()

        # Use a specific checkpoint ID that both operations will target
        checkpoint_id = str(uuid6(clock_seq=-2))

        # Track exceptions and completion
        exceptions = []
        completed = []

        async def put():
            config = {
                "configurable": {
                    "thread_id": str(thread.id),
                    "checkpoint_ns": "",
                }
            }
            checkpoint = {
                "v": 1,
                "ts": "2024-07-31T20:14:19.804150+00:00",
                "id": checkpoint_id,
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
            metadata = {"source": "thread_put"}
            await saver.aput(config, checkpoint, metadata, {})

        async def put_writes():
            config = {
                "configurable": {
                    "thread_id": str(thread.id),
                    "checkpoint_ns": "",
                    "checkpoint_id": checkpoint_id,
                }
            }
            writes = [
                ("thread_channel1", "thread_value_1"),
                ("thread_channel2", "thread_value_2"),
            ]
            await saver.aput_writes(config, writes, str(uuid4()))

        async def get_list():
            return [record async for record in saver.alist({"configurable": {"thread_id": str(thread.id)}})]

        async def delayed_get_list():
            await asyncio.sleep(0.001)
            return [record async for record in saver.alist({"configurable": {"thread_id": str(thread.id)}})]

        # Run the test multiple times
        for attempt in range(10):
            # Clear state
            await ConversationCheckpoint.objects.filter(thread=thread).adelete()
            exceptions.clear()
            completed.clear()

            # Create and start threads
            await asyncio.gather(put(), put_writes(), get_list(), delayed_get_list())

            # Verify checkpoint exists
            checkpoint = await ConversationCheckpoint.objects.filter(thread=thread, id=checkpoint_id).afirst()
            self.assertIsNotNone(checkpoint, f"Checkpoint not found on attempt {attempt + 1}")

            # Verify writes exist
            writes_count = await ConversationCheckpointWrite.objects.filter(checkpoint=checkpoint).acount()
            self.assertEqual(writes_count, 2, f"Expected 2 writes, got {writes_count} on attempt {attempt + 1}")

    async def test_null_checkpoint_not_retrieved(self):
        """Test that checkpoints with null checkpoint field cannot be retrieved."""
        thread = await Conversation.objects.acreate(user=self.user, team=self.team)
        saver = DjangoCheckpointer()

        # Create a checkpoint with valid data first
        valid_checkpoint = {
            "v": 1,
            "ts": "2024-07-31T20:14:19.804150+00:00",
            "id": str(uuid6(clock_seq=-2)),
            "channel_values": {},
            "channel_versions": {},
            "versions_seen": {},
            "pending_sends": [],
        }
        valid_metadata = {"source": "valid"}
        config = {"configurable": {"thread_id": str(thread.id), "checkpoint_ns": ""}}
        await saver.aput(config, valid_checkpoint, valid_metadata, {})

        # Create a checkpoint directly in DB with null checkpoint field
        null_checkpoint = await ConversationCheckpoint.objects.acreate(
            id=str(uuid6(clock_seq=-3)),
            thread=thread,
            checkpoint_ns="",
            checkpoint=None,  # This should make it non-retrievable
            metadata={"source": "null_checkpoint"},
        )

        # Verify the null checkpoint exists in the database
        self.assertEqual(await ConversationCheckpoint.objects.filter(thread=thread).acount(), 2)

        # Try to retrieve checkpoints using the saver
        retrieved_checkpoints = [result async for result in saver.alist(config)]

        # Should only get the valid checkpoint, not the null one
        self.assertEqual(len(retrieved_checkpoints), 1)
        self.assertEqual(retrieved_checkpoints[0].metadata["source"], "valid")

        # Try to get the specific null checkpoint directly
        null_config = {
            "configurable": {"thread_id": str(thread.id), "checkpoint_ns": "", "checkpoint_id": str(null_checkpoint.id)}
        }
        retrieved_null = await saver.aget_tuple(null_config)
        self.assertIsNone(retrieved_null)
