import json
import pytest
from unittest.mock import patch
from ee.hogai.django_checkpoint.serializer import CheckpointSerializer
from ee.hogai.utils.types import AssistantState
from posthog.schema import HumanMessage, AssistantMessage
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


class TestCheckpointSerializer:
    def test_init(self):
        """Test serializer initialization."""
        serializer = CheckpointSerializer()
        assert serializer.legacy is not None
        assert isinstance(serializer.legacy, JsonPlusSerializer)
        assert serializer.migration_registry is not None
        assert serializer.class_registry is not None
        assert serializer.DATA_TYPE == "json"

    def test_dumps_none(self):
        """Test serializing None."""
        serializer = CheckpointSerializer()
        type_str, blob = serializer.dumps_typed(None)
        assert type_str == "json"
        assert json.loads(blob.decode("utf-8")) is None

    def test_dumps_pydantic_model(self):
        """Test serializing a Pydantic model."""
        serializer = CheckpointSerializer()
        state = AssistantState(messages=[HumanMessage(content="Hello")], start_id="test_123")

        type_str, blob = serializer.dumps_typed(state)
        assert type_str == "json"

        checkpoint = json.loads(blob.decode("utf-8"))
        assert "_type" in checkpoint
        assert checkpoint["_type"] == "AssistantState"
        assert "_version" in checkpoint
        assert "_data" in checkpoint

        data = checkpoint["_data"]
        assert "messages" in data
        assert len(data["messages"]) == 1
        assert data["messages"][0]["_type"] == "HumanMessage"
        assert data["start_id"] == "test_123"

    def test_dumps_nested_pydantic_objects(self):
        """Test that nested Pydantic objects get _type field."""
        serializer = CheckpointSerializer()
        state = AssistantState(
            messages=[HumanMessage(content="Hello"), AssistantMessage(content="Hi there!")], start_id="test_nested"
        )

        type_str, blob = serializer.dumps_typed(state)
        checkpoint = json.loads(blob.decode("utf-8"))

        messages = checkpoint["_data"]["messages"]
        assert messages[0]["_type"] == "HumanMessage"
        assert messages[0]["content"] == "Hello"
        assert messages[1]["_type"] == "AssistantMessage"
        assert messages[1]["content"] == "Hi there!"

    def test_dumps_dict(self):
        """Test serializing a plain dict."""
        serializer = CheckpointSerializer()
        data = {"key": "value", "number": 42}

        type_str, blob = serializer.dumps_typed(data)
        assert type_str == "json"

        checkpoint = json.loads(blob.decode("utf-8"))
        assert checkpoint["_type"] == "dict"
        assert checkpoint["_data"] == data

    def test_loads_typed_json(self):
        """Test deserializing our JSON format."""
        serializer = CheckpointSerializer()

        # Create test data
        checkpoint = {
            "_type": "AssistantState",
            "_version": 1,
            "_data": {
                "_type": "AssistantState",
                "messages": [{"_type": "HumanMessage", "content": "Test", "type": "human"}],
                "start_id": "test_456",
            },
        }

        blob = json.dumps(checkpoint).encode("utf-8")
        result = serializer.loads_typed(("json", blob))

        assert isinstance(result, AssistantState)
        assert len(result.messages) == 1
        assert isinstance(result.messages[0], HumanMessage)
        assert result.start_id == "test_456"

    def test_loads_typed_with_migration(self):
        """Test that migrations are applied during deserialization."""
        serializer = CheckpointSerializer()

        # Create a mock migration class
        from ee.hogai.django_checkpoint.migrations.base import BaseMigration

        class MockMigration(BaseMigration):
            def migrate_data(self, data, type_hint):
                data["start_id"] = "migrated"
                return data, type_hint

        # Return the class, not an instance
        with patch.object(serializer.migration_registry, "get_migrations_needed", return_value=[MockMigration]):
            checkpoint = {
                "_type": "AssistantState",
                "_version": 0,  # Old version
                "_data": {"_type": "AssistantState", "messages": [], "start_id": "original"},
            }

            blob = json.dumps(checkpoint).encode("utf-8")
            result = serializer.loads_typed(("json", blob))

            # Migration should have been applied
            assert result.start_id == "migrated"

    def test_loads_legacy_msgpack(self):
        """Test loading legacy msgpack data."""
        serializer = CheckpointSerializer()

        # Create legacy data using JsonPlusSerializer
        legacy = JsonPlusSerializer()
        state = AssistantState(messages=[HumanMessage(content="Legacy message")], start_id="legacy_123")
        type_str, blob = legacy.dumps_typed(state)

        # Load with our serializer
        result = serializer.loads_typed((type_str, blob))

        assert isinstance(result, AssistantState)
        assert len(result.messages) == 1
        assert result.start_id == "legacy_123"

    def test_loads_legacy_with_migration(self):
        """Test that legacy data triggers migrations."""
        serializer = CheckpointSerializer()

        # Create legacy data
        legacy = JsonPlusSerializer()
        state = AssistantState(messages=[HumanMessage(content="Legacy")], start_id="legacy_456")
        type_str, blob = legacy.dumps_typed(state)

        # Create a mock migration class
        from ee.hogai.django_checkpoint.migrations.base import BaseMigration

        class MockMigration(BaseMigration):
            def migrate_data(self, data, type_hint):
                # Just return the data as-is
                return data, type_hint

        with patch.object(serializer.migration_registry, "get_migrations_needed", return_value=[MockMigration]):
            result = serializer.loads_typed((type_str, blob))

            # For legacy data without version_metadata, migrations should apply
            assert isinstance(result, AssistantState)

    def test_roundtrip_assistant_state(self):
        """Test serializing and deserializing AssistantState."""
        serializer = CheckpointSerializer()

        original = AssistantState(
            messages=[HumanMessage(content="Question"), AssistantMessage(content="Answer")],
            start_id="roundtrip_123",
            graph_status="interrupted",
        )

        # Serialize
        type_str, blob = serializer.dumps_typed(original)

        # Deserialize
        restored = serializer.loads_typed((type_str, blob))

        assert isinstance(restored, AssistantState)
        assert len(restored.messages) == 2
        assert restored.messages[0].content == "Question"
        assert restored.messages[1].content == "Answer"
        assert restored.start_id == "roundtrip_123"
        assert restored.graph_status == "interrupted"

    def test_handles_unknown_type(self):
        """Test handling unknown types."""
        serializer = CheckpointSerializer()

        checkpoint = {
            "_type": "UnknownStateType",
            "_version": 1,
            "_data": {"_type": "UnknownStateType", "field1": "value1", "field2": "value2"},
        }

        blob = json.dumps(checkpoint).encode("utf-8")
        result = serializer.loads_typed(("json", blob))

        # Should return as dict if type not found
        assert isinstance(result, dict)
        assert result["field1"] == "value1"
        assert result["field2"] == "value2"

    def test_loads_with_real_legacy_fixture(self):
        """Test loading real legacy checkpoint data from fixture."""
        import os

        fixture_path = os.path.join(os.path.dirname(__file__), "./legacy_checkpoint_fixtures.json")

        with open(fixture_path) as f:
            fixtures = json.load(f)

        serializer = CheckpointSerializer()

        # Test with first checkpoint's write data
        first_checkpoint = fixtures[0]["checkpoints"][0]
        write_data = first_checkpoint["metadata"]["writes"]["__start__"]

        # This is in LangChain format with id, lc, type, kwargs
        assert write_data["id"] == ["ee", "hogai", "utils", "types", "AssistantState"]
        assert "messages" in write_data["kwargs"]
        assert write_data["kwargs"]["start_id"] == "16f26ac5-9f79-4e67-86ee-951b72027a5a"

        # Test that we can handle the kwargs structure
        state_data = write_data["kwargs"]
        state_data["_type"] = "AssistantState"

        # Create a checkpoint format
        checkpoint = {"_type": "AssistantState", "_version": 1, "_data": state_data}

        blob = json.dumps(checkpoint).encode("utf-8")
        result = serializer.loads_typed(("json", blob))

        assert isinstance(result, AssistantState)
        assert len(result.messages) == 1
        assert result.messages[0].content == "What's my conversion rate on signup"
        assert result.start_id == "16f26ac5-9f79-4e67-86ee-951b72027a5a"

    def test_error_handling_in_deserialization(self):
        """Test error handling during deserialization."""
        serializer = CheckpointSerializer()

        # Test with invalid JSON
        with pytest.raises(json.JSONDecodeError):
            serializer.loads_typed(("json", b"invalid json"))

        # Test with missing _data
        checkpoint = {
            "_type": "AssistantState",
            "_version": 1,
            # missing _data
        }
        blob = json.dumps(checkpoint).encode("utf-8")
        result = serializer.loads_typed(("json", blob))
        # Should handle gracefully by creating object with defaults
        assert isinstance(result, AssistantState)
        assert result.messages == []  # Default value for messages field

    def test_version_tracking(self):
        """Test that version is properly tracked."""
        serializer = CheckpointSerializer()

        state = AssistantState(messages=[], start_id="version_test")

        type_str, blob = serializer.dumps_typed(state)
        checkpoint = json.loads(blob.decode("utf-8"))

        assert "_version" in checkpoint
        assert isinstance(checkpoint["_version"], int)
        assert checkpoint["_version"] == serializer.migration_registry.current_version
