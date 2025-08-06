"""
Tests for ClassRegistry.

Tests auto-discovery, class construction, and nested object handling.
"""

from ee.hogai.django_checkpoint.class_registry import ClassRegistry, class_registry
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import HumanMessage, AssistantMessage
from pydantic import BaseModel


class TestClassRegistry:
    def test_get_class_finds_cached_class(self):
        """Test getting a cached class."""
        registry = ClassRegistry()

        # Manually add to cache for testing
        mock_class = type("TestState", (BaseModel,), {})
        registry._cache["TestState"] = mock_class

        result = registry.get_class("TestState")
        assert result is mock_class

    def test_get_class_returns_none_for_unknown(self):
        """Test that unknown classes return None."""
        registry = ClassRegistry()
        result = registry.get_class("NonExistentClass")
        assert result is None

    def test_construct_with_known_class(self):
        """Test constructing an object with a known class."""
        registry = ClassRegistry()

        # Use real AssistantState
        data = {"_type": "AssistantState", "messages": [], "start_id": "test_123"}

        result = registry.construct("AssistantState", data)
        assert isinstance(result, AssistantState)
        assert result.start_id == "test_123"
        assert result.messages == []

    def test_construct_with_nested_pydantic_objects(self):
        """Test constructing with nested Pydantic objects."""
        registry = ClassRegistry()

        data = {
            "_type": "AssistantState",
            "messages": [
                {"_type": "HumanMessage", "content": "Hello", "type": "human"},
                {"_type": "AssistantMessage", "content": "Hi!", "type": "ai"},
            ],
            "start_id": "nested_test",
        }

        result = registry.construct("AssistantState", data)
        assert isinstance(result, AssistantState)
        assert len(result.messages) == 2
        assert isinstance(result.messages[0], HumanMessage)
        assert isinstance(result.messages[1], AssistantMessage)
        assert result.messages[0].content == "Hello"
        assert result.messages[1].content == "Hi!"

    def test_construct_returns_dict_for_unknown_class(self):
        """Test that unknown classes return the data as dict."""
        registry = ClassRegistry()

        data = {"_type": "UnknownClass", "field1": "value1", "field2": 42}

        result = registry.construct("UnknownClass", data)
        assert result == data
        assert isinstance(result, dict)

    def test_process_nested_objects_recursive(self):
        """Test recursive processing of nested objects."""
        registry = ClassRegistry()

        # Complex nested structure
        data = {
            "outer": {"_type": "HumanMessage", "content": "Nested message", "type": "human"},
            "list_field": [
                {"_type": "AssistantMessage", "content": "Item 1", "type": "ai"},
                {"regular": "dict"},
                "string value",
            ],
            "regular_field": "value",
        }

        result = registry._process_nested_objects(data)

        # Check outer object was constructed
        assert isinstance(result["outer"], HumanMessage)
        assert result["outer"].content == "Nested message"

        # Check list items
        assert isinstance(result["list_field"][0], AssistantMessage)
        assert result["list_field"][1] == {"regular": "dict"}
        assert result["list_field"][2] == "string value"

        # Regular field unchanged
        assert result["regular_field"] == "value"

    def test_process_nested_handles_construction_failure(self):
        """Test that construction failures don't break processing."""
        registry = ClassRegistry()

        # Data with invalid structure for the type
        data = {
            "_type": "HumanMessage",
            # Missing required fields - should fail construction
            "invalid": "data",
        }

        result = registry._process_nested_objects(data)

        # Should return original dict with _type restored
        assert isinstance(result, dict)
        assert result["_type"] == "HumanMessage"
        assert result["invalid"] == "data"

    def test_construct_with_partial_assistant_state(self):
        """Test constructing PartialAssistantState."""
        registry = ClassRegistry()

        data = {
            "_type": "PartialAssistantState",
            "messages": [{"_type": "AssistantMessage", "content": "Update", "type": "ai"}],
        }

        result = registry.construct("PartialAssistantState", data)
        assert isinstance(result, PartialAssistantState)
        assert len(result.messages) == 1
        assert isinstance(result.messages[0], AssistantMessage)

    def test_singleton_instance(self):
        """Test that the global class_registry instance works."""
        # This uses the actual global instance

        # Should be able to construct known classes
        data = {"_type": "HumanMessage", "content": "Test global", "type": "human"}

        result = class_registry.construct("HumanMessage", data)
        assert isinstance(result, HumanMessage)
        assert result.content == "Test global"

    def test_handles_missing_type_field(self):
        """Test handling data without _type field."""
        registry = ClassRegistry()

        data = {"messages": [], "start_id": "no_type"}

        result = registry.construct("AssistantState", data)
        assert isinstance(result, AssistantState)
        assert result.start_id == "no_type"

    def test_handles_primitive_values(self):
        """Test that primitive values pass through unchanged."""
        registry = ClassRegistry()

        assert registry._process_nested_objects("string") == "string"
        assert registry._process_nested_objects(42) == 42
        assert registry._process_nested_objects(True) is True
        assert registry._process_nested_objects(None) is None

    def test_construct_with_real_legacy_data(self):
        """Test with data structure from legacy fixtures."""
        registry = ClassRegistry()

        # Structure similar to legacy checkpoint data
        data = {
            "_type": "AssistantState",
            "messages": [
                {
                    "id": "16f26ac5-9f79-4e67-86ee-951b72027a5a",
                    "type": "human",
                    "content": "What's my conversion rate on signup",
                    "ui_context": None,
                }
            ],
            "start_id": "16f26ac5-9f79-4e67-86ee-951b72027a5a",
            "plan": None,
            "rag_context": None,
            "graph_status": None,
        }

        result = registry.construct("AssistantState", data)
        assert isinstance(result, AssistantState)
        assert len(result.messages) == 1
        # Note: Pydantic can infer HumanMessage from the fields even without _type
        assert isinstance(result.messages[0], HumanMessage)
        assert result.messages[0].content == "What's my conversion rate on signup"

    def test_deeply_nested_structures(self):
        """Test very deep nesting."""
        registry = ClassRegistry()

        data = {"level1": {"level2": {"level3": {"_type": "HumanMessage", "content": "Deep", "type": "human"}}}}

        result = registry._process_nested_objects(data)
        assert isinstance(result["level1"]["level2"]["level3"], HumanMessage)
        assert result["level1"]["level2"]["level3"].content == "Deep"

    def test_mixed_list_types(self):
        """Test lists with mixed types."""
        registry = ClassRegistry()

        data = {
            "mixed": [
                {"_type": "HumanMessage", "content": "First", "type": "human"},
                "plain string",
                42,
                {"plain": "dict"},
                None,
                {"_type": "AssistantMessage", "content": "Last", "type": "ai"},
            ]
        }

        result = registry._process_nested_objects(data)
        assert isinstance(result["mixed"][0], HumanMessage)
        assert result["mixed"][1] == "plain string"
        assert result["mixed"][2] == 42
        assert result["mixed"][3] == {"plain": "dict"}
        assert result["mixed"][4] is None
        assert isinstance(result["mixed"][5], AssistantMessage)
