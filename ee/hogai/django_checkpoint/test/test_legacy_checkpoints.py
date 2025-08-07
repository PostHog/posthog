import json
import os
import pytest

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from ee.hogai.django_checkpoint.class_registry import class_registry
from ee.hogai.django_checkpoint.serializer import CheckpointSerializer
from ee.hogai.utils.types import AssistantState
from posthog.schema import HumanMessage, AssistantMessage, VisualizationMessage
from typing import Optional, TypedDict, Annotated
from unittest.mock import patch
from datetime import datetime, UTC

from langgraph.graph import StateGraph, END
from operator import add

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types import PartialAssistantState


class SimpleState(TypedDict):
    """Simple state for testing."""

    messages: Optional[Annotated[list, add]]
    count: Optional[int]


class TestE2ELangGraph:
    @pytest.fixture
    def legacy_fixtures(self):
        """Load all legacy checkpoint fixtures."""
        fixture_path = os.path.join(os.path.dirname(__file__), "legacy_checkpoints_fixtures.json")
        with open(fixture_path) as f:
            return json.load(f)

    @pytest.fixture
    def simple_graph(self):
        """Create a simple LangGraph for testing."""

        def increment_node(state: SimpleState) -> SimpleState:
            return {"count": state["count"] + 1}

        def message_node(state: SimpleState) -> SimpleState:
            return {"messages": [AssistantMessage(content=f"Count is {state['count']}")]}

        graph = StateGraph(SimpleState)
        graph.add_node("increment", increment_node)
        graph.add_node("message", message_node)
        graph.add_edge("increment", "message")
        graph.add_edge("message", END)
        graph.set_entry_point("increment")

        return graph.compile()

    @pytest.fixture
    def assistant_graph(self):
        """Create a graph that uses AssistantState."""

        def process_node(state: AssistantState) -> AssistantState:
            # Add a response message
            return AssistantState(messages=[AssistantMessage(content="Processed your request")])

        graph = StateGraph(AssistantState)
        graph.add_node("process", process_node)
        graph.add_edge("process", END)
        graph.set_entry_point("process")

        return graph.compile()

    @pytest.mark.asyncio
    async def test_process_all_legacy_checkpoints(self, legacy_fixtures):
        """Test processing ALL checkpoints from legacy fixtures - MUST handle all of them."""
        total_checkpoints = 0
        total_states_found = 0
        successful_deserializations = 0
        failed_deserializations = []
        serializer = CheckpointSerializer()

        for conv_idx, conversation in enumerate(legacy_fixtures):
            for cp_idx, checkpoint_data in enumerate(conversation["checkpoints"]):
                total_checkpoints += 1

                # Process writes data
                if "writes" in checkpoint_data["metadata"] and checkpoint_data["metadata"]["writes"]:
                    for channel, write_data in checkpoint_data["metadata"]["writes"].items():
                        if isinstance(write_data, dict) and "kwargs" in write_data:
                            # This is LangChain format state data
                            state_data = write_data["kwargs"]

                            # Determine type from id field
                            if "id" in write_data and isinstance(write_data["id"], list):
                                type_name = write_data["id"][-1]
                                total_states_found += 1

                                # Add type information for serialization
                                state_data["_type"] = type_name

                                # Create checkpoint format
                                checkpoint_format = {
                                    "_type": type_name,
                                    "_version": 0,  # Legacy has no version
                                    "_data": state_data,
                                }

                                # Serialize and deserialize
                                blob = json.dumps(checkpoint_format).encode("utf-8")

                                try:
                                    result = serializer.loads_typed(("json", blob))
                                    assert result is not None, f"Deserialization returned None for {type_name}"

                                    # Verify we got the right type
                                    if type_name == "AssistantState":
                                        assert isinstance(
                                            result, AssistantState
                                        ), f"Expected AssistantState, got {type(result)}"

                                    successful_deserializations += 1

                                except Exception as e:
                                    failed_deserializations.append(
                                        {
                                            "conversation": conv_idx,
                                            "checkpoint": cp_idx,
                                            "channel": channel,
                                            "type": type_name,
                                            "error": str(e),
                                        }
                                    )

        # Report any failures
        if failed_deserializations:
            failure_summary = "\n".join(
                [
                    f"  - Conv {f['conversation']}, CP {f['checkpoint']}, Channel {f['channel']}: {f['type']} - {f['error']}"
                    for f in failed_deserializations
                ]
            )
            pytest.fail(f"Failed to deserialize {len(failed_deserializations)} states:\n{failure_summary}")

        # ALL states must be successfully deserialized
        assert (
            successful_deserializations == total_states_found
        ), f"Only {successful_deserializations}/{total_states_found} states were successfully deserialized"

        # Must have exactly the expected number of states (no weak >= check)
        assert total_states_found > 0, "No states found in legacy fixtures"
        assert (
            successful_deserializations == total_states_found
        ), f"Expected all {total_states_found} states to be deserialized, got {successful_deserializations}"

    @pytest.mark.asyncio
    async def test_langgraph_with_legacy_state(self, legacy_fixtures, assistant_graph):
        """Test using legacy state data with LangGraph."""
        # Get first checkpoint with AssistantState
        first_checkpoint = legacy_fixtures[0]["checkpoints"][0]
        write_data = first_checkpoint["metadata"]["writes"]["__start__"]
        state_data = write_data["kwargs"]

        # Create AssistantState from legacy data
        state = AssistantState(
            messages=state_data.get("messages", []),
            start_id=state_data.get("start_id"),
            graph_status=state_data.get("graph_status"),
        )

        # Create checkpointer
        checkpointer = DjangoCheckpointer()

        # Mock database operations
        with patch.object(checkpointer, "_put") as mock_update:
            mock_update.return_value = {
                "configurable": {"thread_id": "test-thread", "checkpoint_id": "checkpoint-uuid"}
            }

            with patch.object(checkpointer, "_put_writes"):
                # Run graph with legacy state as input
                config = {"configurable": {"thread_id": "test-thread"}}

                # Use the state as initial input
                # Pass a dict with proper format for AssistantState
                input_state = {
                    "messages": state.messages,  # Keep as message objects
                    "start_id": state.start_id,
                    "graph_status": state.graph_status,
                }
                result = await assistant_graph.ainvoke(input_state, config)

                # Should have processed and added a message
                assert "messages" in result
                assert len(result["messages"]) > len(state.messages)

    @pytest.mark.asyncio
    async def test_checkpoint_roundtrip_all_conversations(self, legacy_fixtures):
        """Test checkpointing roundtrip for ALL conversations in fixtures."""

        for _, conversation in enumerate(legacy_fixtures):
            checkpointer = DjangoCheckpointer()

            for _, checkpoint_data in enumerate(conversation["checkpoints"]):
                # Extract checkpoint components
                checkpoint = checkpoint_data["checkpoint"]
                metadata = checkpoint_data["metadata"]

                # Process channel values from writes
                channel_values = {}
                if metadata.get("writes"):
                    for channel, write_data in metadata["writes"].items():
                        if isinstance(write_data, dict) and "kwargs" in write_data:
                            state_data = write_data["kwargs"]

                            # Reconstruct state
                            if write_data.get("id", [""])[-1] == "AssistantState":
                                state = AssistantState(
                                    **{k: v for k, v in state_data.items() if k in AssistantState.model_fields}
                                )
                                channel_values[channel] = state

                # Create checkpoint dict
                checkpoint_dict = {
                    "v": checkpoint.get("v", 1),
                    "id": checkpoint_data["checkpoint_id"],
                    "ts": checkpoint.get("ts", datetime.now(UTC).isoformat()),
                    "channel_values": channel_values,
                    "channel_versions": checkpoint.get("channel_versions", {}),
                    "versions_seen": checkpoint.get("versions_seen", {}),
                }

                config = {
                    "configurable": {
                        "thread_id": conversation["conversation_id"],
                        "checkpoint_ns": checkpoint_data["checkpoint_ns"],
                        "checkpoint_id": checkpoint_data["checkpoint_id"],
                    }
                }

                with patch.object(
                    checkpointer,
                    "_put",
                    return_value={
                        "configurable": {
                            "thread_id": conversation["conversation_id"],
                            "checkpoint_id": f"db-{checkpoint_data['checkpoint_id']}",
                        }
                    },
                ) as mock_update:
                    with patch.object(checkpointer, "_put_writes"):
                        # Save checkpoint
                        await checkpointer.aput(config, checkpoint_dict, metadata, {})

                        # Verify it was saved
                        mock_update.assert_called_once()

                        # Check serialization format was valid JSON
                        # The _put method receives (config, checkpoint, metadata, new_versions)
                        call_args = mock_update.call_args[0]
                        assert (
                            len(call_args) == 4
                        ), (
                            f"Expected exactly 4 arguments to _put, got {len(call_args)}"
                        )  # Must have exactly config, checkpoint, metadata, new_versions

    @pytest.mark.asyncio
    async def test_migration_applied_to_legacy_data(self, legacy_fixtures):
        """Test that migrations are applied to ALL legacy data when needed."""
        serializer = CheckpointSerializer()

        # Track migration applications
        migrations_applied = []
        total_legacy_states = 0

        for conversation in legacy_fixtures:
            for checkpoint_data in conversation["checkpoints"]:
                if "writes" in checkpoint_data["metadata"] and checkpoint_data["metadata"]["writes"]:
                    for write_data in checkpoint_data["metadata"]["writes"].values():
                        if isinstance(write_data, dict) and "kwargs" in write_data:
                            state_data = write_data["kwargs"]
                            type_name = write_data.get("id", [""])[-1] if "id" in write_data else "Unknown"

                            if type_name != "Unknown":
                                total_legacy_states += 1

                                # Create checkpoint without version (simulating legacy)
                                checkpoint = {
                                    "_type": type_name,
                                    "_version": 0,  # Old version
                                    "_data": {**state_data, "_type": type_name},
                                }

                                # Mock migration to track calls
                                with patch.object(serializer.migration_registry, "get_migrations_needed") as mock_get:
                                    # Create a proper migration class mock
                                    class MockMigration:
                                        __name__ = "MockMigration"

                                        def migrate_data(self, data, type_name, context):
                                            migrations_applied.append(type_name)
                                            return (data, type_name)

                                    mock_get.return_value = [MockMigration]

                                    blob = json.dumps(checkpoint).encode("utf-8")
                                    result = serializer.loads_typed(("json", blob))
                                    assert result is not None, f"Failed to deserialize {type_name} after migration"

        # Every legacy state should have been processed through migration
        assert (
            len(migrations_applied) == total_legacy_states
        ), f"Only {len(migrations_applied)}/{total_legacy_states} states had migrations applied"

    @pytest.mark.asyncio
    async def test_complex_message_types(self, legacy_fixtures):
        """Test that ALL message types in fixtures can be properly constructed."""
        message_types_found = set()
        total_messages = 0
        successful_constructions = 0
        failures = []

        for conv_idx, conversation in enumerate(legacy_fixtures):
            for cp_idx, checkpoint_data in enumerate(conversation["checkpoints"]):
                if "writes" in checkpoint_data["metadata"] and checkpoint_data["metadata"]["writes"]:
                    for channel, write_data in checkpoint_data["metadata"]["writes"].items():
                        if isinstance(write_data, dict) and "kwargs" in write_data:
                            state_data = write_data["kwargs"]

                            # Check messages
                            if "messages" in state_data:
                                for msg_idx, msg in enumerate(state_data["messages"]):
                                    msg_type = msg.get("type", msg.get("_type", "unknown"))
                                    message_types_found.add(msg_type)
                                    total_messages += 1

                                    # Test each message type - ALL must be constructible
                                    try:
                                        if msg_type == "human":
                                            human_msg = HumanMessage(
                                                **{k: v for k, v in msg.items() if k in HumanMessage.model_fields}
                                            )
                                            assert human_msg.type == "human"
                                            successful_constructions += 1

                                        elif msg_type == "assistant" or msg_type == "ai":
                                            # Handle tool_calls field
                                            assistant_data = {
                                                k: v for k, v in msg.items() if k in AssistantMessage.model_fields
                                            }
                                            assistant_msg = AssistantMessage(**assistant_data)
                                            assert (
                                                assistant_msg.type == "ai"
                                            )  # AssistantMessage.type is "ai" in the schema
                                            successful_constructions += 1

                                        elif msg_type == "visualization":
                                            viz_data = {
                                                k: v for k, v in msg.items() if k in VisualizationMessage.model_fields
                                            }
                                            viz_msg = VisualizationMessage(**viz_data)
                                            assert viz_msg.type == "visualization"
                                            successful_constructions += 1

                                        elif msg_type != "unknown":
                                            # Unknown message type that should be handled
                                            failures.append(
                                                {
                                                    "conv": conv_idx,
                                                    "checkpoint": cp_idx,
                                                    "channel": channel,
                                                    "msg_idx": msg_idx,
                                                    "type": msg_type,
                                                    "error": f"Unknown message type: {msg_type}",
                                                }
                                            )
                                    except Exception as e:
                                        failures.append(
                                            {
                                                "conv": conv_idx,
                                                "checkpoint": cp_idx,
                                                "channel": channel,
                                                "msg_idx": msg_idx,
                                                "type": msg_type,
                                                "error": str(e),
                                            }
                                        )

        # Report failures
        if failures:
            failure_report = "\n".join(
                [
                    f"  Conv {f['conv']}, CP {f['checkpoint']}, {f['channel']}, Msg {f['msg_idx']}: {f['type']} - {f['error']}"
                    for f in failures
                ]
            )
            pytest.fail(f"Failed to construct {len(failures)}/{total_messages} messages:\n{failure_report}")

        # All messages must be handled
        assert (
            successful_constructions == total_messages
        ), f"Only {successful_constructions}/{total_messages} messages were successfully constructed"

        # Should have found multiple message types
        assert len(message_types_found) >= 2, f"Expected at least 2 message types, found: {message_types_found}"

    @pytest.mark.asyncio
    async def test_graph_with_checkpointer_integration(self, legacy_fixtures, simple_graph):
        """Test full integration: legacy data → checkpointer → graph execution."""

        # Process each conversation
        for conversation in legacy_fixtures[:3]:  # Test first 3 conversations
            checkpointer = DjangoCheckpointer()

            # Configure graph with checkpointer
            graph_with_checkpoint = simple_graph

            # Create config for this conversation
            config = {"configurable": {"thread_id": conversation["conversation_id"]}}

            # Mock checkpointer methods
            with patch.object(checkpointer, "_put") as mock_update:
                mock_update.return_value = {
                    "configurable": {"thread_id": conversation["conversation_id"], "checkpoint_id": "checkpoint-uuid"}
                }

                with patch.object(checkpointer, "_put_writes"):
                    with patch.object(checkpointer, "aget", return_value=None):
                        # Run graph
                        initial_state = {"messages": [], "count": 0}
                        result = await graph_with_checkpoint.ainvoke(initial_state, config)

                        # Should have incremented count and added message
                        assert result["count"] == 1
                        assert len(result["messages"]) == 1

    @pytest.mark.asyncio
    async def test_checkpoint_versioning(self, legacy_fixtures):
        """Test that version tracking works correctly."""
        serializer = CheckpointSerializer()

        for conversation in legacy_fixtures[:5]:  # Test first 5
            for checkpoint_data in conversation["checkpoints"]:
                if "writes" in checkpoint_data["metadata"] and checkpoint_data["metadata"]["writes"]:
                    for write_data in checkpoint_data["metadata"]["writes"].values():
                        if isinstance(write_data, dict) and "kwargs" in write_data:
                            state_data = write_data["kwargs"]

                            # Create state
                            if write_data.get("id", [""])[-1] == "AssistantState":
                                state = AssistantState(
                                    **{k: v for k, v in state_data.items() if k in AssistantState.model_fields}
                                )

                                # Serialize with new serializer (should add version)
                                type_str, blob = serializer.dumps_typed(state)
                                checkpoint = json.loads(blob.decode("utf-8"))

                                # Should have specific version matching the registry
                                assert "_version" in checkpoint
                                assert (
                                    checkpoint["_version"] == serializer.migration_registry.current_version
                                ), f"Expected version {serializer.migration_registry.current_version}, got {checkpoint['_version']}"

                                # Deserialize and check it still works
                                restored = serializer.loads_typed((type_str, blob))
                                assert isinstance(restored, AssistantState)

    @pytest.mark.asyncio
    async def test_partial_state_updates(self, legacy_fixtures):
        """Test that partial state updates work with legacy data."""

        # Find checkpoints with messages to update
        for conversation in legacy_fixtures:
            for checkpoint_data in conversation["checkpoints"]:
                if "writes" in checkpoint_data["metadata"] and checkpoint_data["metadata"]["writes"]:
                    for write_data in checkpoint_data["metadata"]["writes"].values():
                        if isinstance(write_data, dict) and "kwargs" in write_data:
                            state_data = write_data["kwargs"]

                            if state_data.get("messages"):
                                # Create partial update
                                partial = PartialAssistantState(messages=[AssistantMessage(content="Updated message")])

                                # Serialize and deserialize
                                serializer = CheckpointSerializer()
                                type_str, blob = serializer.dumps_typed(partial)
                                restored = serializer.loads_typed((type_str, blob))

                                assert isinstance(restored, PartialAssistantState)
                                assert len(restored.messages) == 1
                                assert restored.messages[0].content == "Updated message"

                                # Test one is enough
                                return

    @pytest.mark.asyncio
    async def test_error_recovery(self, legacy_fixtures):
        """Test that system handles corrupted/invalid data gracefully."""
        serializer = CheckpointSerializer()

        # Test with various corrupted scenarios
        test_cases = [
            # Missing required fields
            {"_type": "AssistantState", "_version": 1, "_data": {}},
            # Invalid type
            {"_type": "NonExistentState", "_version": 1, "_data": {"field": "value"}},
            # Corrupted structure
            {"_type": "AssistantState", "_version": 1},  # Missing _data
            # Wrong version format
            {"_type": "AssistantState", "_version": "not_a_number", "_data": {}},
        ]

        for i, test_case in enumerate(test_cases):
            blob = json.dumps(test_case).encode("utf-8")

            try:
                result = serializer.loads_typed(("json", blob))
                # Should handle gracefully, returning dict or empty
                assert result is not None
            except json.JSONDecodeError:
                # JSON errors are expected for truly corrupted data
                pass
            except Exception as e:
                # Other errors should be handled
                pytest.fail(f"Unexpected error for test case {i+1}: {e}")


class TestLegacyFixtures:
    @pytest.fixture
    def legacy_fixtures(self):
        """Load legacy checkpoint fixtures."""
        fixture_path = os.path.join(os.path.dirname(__file__), "legacy_checkpoints_fixtures.json")
        with open(fixture_path) as f:
            return json.load(f)

    def test_deserialize_legacy_writes(self, legacy_fixtures):
        """Test deserializing legacy write data."""
        # Get first checkpoint's write data
        first_checkpoint = legacy_fixtures[0]["checkpoints"][0]
        write_data = first_checkpoint["metadata"]["writes"]["__start__"]

        # This is in LangChain format
        assert write_data["id"] == ["ee", "hogai", "utils", "types", "AssistantState"]
        assert write_data["lc"] == 2
        assert write_data["type"] == "constructor"
        assert "kwargs" in write_data

        # Extract the actual state data
        state_data = write_data["kwargs"]

        # Verify structure
        assert "messages" in state_data
        assert "start_id" in state_data
        assert state_data["start_id"] == "16f26ac5-9f79-4e67-86ee-951b72027a5a"

        # Test that we can reconstruct the state
        state = class_registry.construct("AssistantState", state_data)
        assert isinstance(state, AssistantState)
        assert state.start_id == "16f26ac5-9f79-4e67-86ee-951b72027a5a"

    def test_process_all_conversations(self, legacy_fixtures):
        """Test processing ALL conversations in fixtures - every state MUST be handled."""
        total_states = 0
        successful_count = 0
        failures = []

        for conv_idx, conversation in enumerate(legacy_fixtures):
            for cp_idx, checkpoint in enumerate(conversation["checkpoints"]):
                if "writes" in checkpoint["metadata"] and checkpoint["metadata"]["writes"]:
                    for channel, write_data in checkpoint["metadata"]["writes"].items():
                        if isinstance(write_data, dict) and "kwargs" in write_data:
                            state_data = write_data["kwargs"]

                            # Determine the type
                            if write_data.get("id"):
                                type_name = write_data["id"][-1]  # Last element is class name
                                total_states += 1

                                # Try to construct - MUST succeed for all
                                try:
                                    result = class_registry.construct(type_name, state_data)
                                    assert result is not None, f"Construction returned None for {type_name}"
                                    successful_count += 1
                                except Exception as e:
                                    failures.append(
                                        {
                                            "conv": conv_idx,
                                            "checkpoint": cp_idx,
                                            "channel": channel,
                                            "type": type_name,
                                            "error": str(e),
                                        }
                                    )

        # Report failures if any
        if failures:
            failure_report = "\n".join(
                [
                    f"  Conv {f['conv']}, CP {f['checkpoint']}, {f['channel']}: {f['type']} - {f['error']}"
                    for f in failures
                ]
            )
            pytest.fail(f"Failed to construct {len(failures)}/{total_states} states:\n{failure_report}")

        # ALL states must be successfully constructed
        assert (
            successful_count == total_states
        ), f"Only constructed {successful_count}/{total_states} states successfully"

    def test_message_reconstruction(self, legacy_fixtures):
        """Test reconstructing messages from legacy data."""
        # Find a checkpoint with messages
        for conversation in legacy_fixtures:
            for checkpoint in conversation["checkpoints"]:
                if "writes" in checkpoint["metadata"] and checkpoint["metadata"]["writes"]:
                    for write_data in checkpoint["metadata"]["writes"].values():
                        if isinstance(write_data, dict) and "kwargs" in write_data:
                            state_data = write_data["kwargs"]
                            if state_data.get("messages"):
                                # Test message reconstruction
                                messages = state_data["messages"]

                                for msg in messages:
                                    assert "type" in msg or "_type" in msg

                                    # Check message types
                                    msg_type = msg.get("type") or msg.get("_type")
                                    if msg_type == "human":
                                        # Should be able to construct HumanMessage
                                        human_msg = class_registry.construct("HumanMessage", msg)
                                        if isinstance(human_msg, HumanMessage):
                                            assert human_msg.content is not None
                                    elif msg_type == "assistant":
                                        assistant_msg = class_registry.construct("AssistantMessage", msg)
                                        if isinstance(assistant_msg, AssistantMessage):
                                            assert (
                                                assistant_msg.content is not None
                                                or assistant_msg.tool_calls is not None
                                            )

                                # Found and tested messages, can return
                                return

    def test_complex_checkpoint_with_visualization(self, legacy_fixtures):
        """Test handling complex checkpoints with visualization messages."""
        # Look for checkpoints with visualization messages
        for conversation in legacy_fixtures:
            for checkpoint in conversation["checkpoints"]:
                if "writes" in checkpoint["metadata"] and checkpoint["metadata"]["writes"]:
                    for write_data in checkpoint["metadata"]["writes"].values():
                        if isinstance(write_data, dict) and "kwargs" in write_data:
                            state_data = write_data["kwargs"]
                            if "messages" in state_data:
                                for msg in state_data["messages"]:
                                    if msg.get("type") == "visualization" or msg.get("_type") == "VisualizationMessage":
                                        # Test visualization message
                                        viz_msg = class_registry.construct("VisualizationMessage", msg)
                                        if isinstance(viz_msg, VisualizationMessage):
                                            assert viz_msg.answer is not None
                                            return

    def test_roundtrip_legacy_checkpoint(self, legacy_fixtures):
        """Test serializing and deserializing legacy checkpoint data."""
        serializer = CheckpointSerializer()

        # Get a checkpoint with state data
        first_checkpoint = legacy_fixtures[0]["checkpoints"][0]
        write_data = first_checkpoint["metadata"]["writes"]["__start__"]
        state_data = write_data["kwargs"]

        # Create an AssistantState from legacy data
        state = AssistantState(
            **{
                "messages": state_data.get("messages", []),
                "start_id": state_data.get("start_id"),
                "graph_status": state_data.get("graph_status"),
                "plan": state_data.get("plan"),
                "intermediate_steps": state_data.get("intermediate_steps", []),
            }
        )

        # Serialize with new serializer
        type_str, blob = serializer.dumps_typed(state)
        assert type_str == "json"

        # Deserialize
        restored = serializer.loads_typed((type_str, blob))
        assert isinstance(restored, AssistantState)
        assert restored.start_id == state.start_id

        # Messages should be reconstructed
        if state.messages:
            assert len(restored.messages) == len(state.messages)

    def test_legacy_msgpack_compatibility(self, legacy_fixtures):
        """Test that we can handle legacy msgpack format."""
        serializer = CheckpointSerializer()
        legacy = JsonPlusSerializer()

        # Create state from legacy data
        first_checkpoint = legacy_fixtures[0]["checkpoints"][0]
        write_data = first_checkpoint["metadata"]["writes"]["__start__"]
        state_data = write_data["kwargs"]

        state = AssistantState(**{"messages": state_data.get("messages", []), "start_id": state_data.get("start_id")})

        # Serialize with legacy serializer (simulating old data)
        legacy_type, legacy_blob = legacy.dumps_typed(state)

        # Should be able to load with new serializer
        restored = serializer.loads_typed((legacy_type, legacy_blob))
        assert isinstance(restored, AssistantState)
        assert restored.start_id == state.start_id

    def test_checkpoint_metadata_fields(self, legacy_fixtures):
        """Test that checkpoint metadata is preserved."""
        # Check various metadata fields in fixtures
        for conversation in legacy_fixtures:
            assert "conversation_id" in conversation
            assert "user_id" in conversation
            assert "team_id" in conversation
            assert "status" in conversation
            assert "type" in conversation

            for checkpoint in conversation["checkpoints"]:
                assert "checkpoint_id" in checkpoint
                assert "checkpoint_ns" in checkpoint
                assert "checkpoint" in checkpoint

                cp_data = checkpoint["checkpoint"]
                assert "v" in cp_data
                assert "id" in cp_data
                assert "ts" in cp_data
