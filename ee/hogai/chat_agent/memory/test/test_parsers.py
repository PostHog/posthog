from posthog.test.base import BaseTest

from langchain_core.messages import AIMessage

from ee.hogai.chat_agent.memory.parsers import MemoryCollectionCompleted, compressed_memory_parser, raise_memory_updated
import pytest


class TestParsers(BaseTest):
    def test_compressed_memory_parser(self):
        memory = "Hello\n\nWorld "
        assert compressed_memory_parser(memory) == "Hello\nWorld "

    def test_raise_memory_updated(self):
        message = AIMessage(content="Hello World")
        with pytest.raises(MemoryCollectionCompleted):
            raise_memory_updated(message)

        message = AIMessage(content="[Done]", tool_calls=[{"id": "1", "args": {}, "name": "function"}])
        with pytest.raises(MemoryCollectionCompleted):
            raise_memory_updated(message)

        message = AIMessage(content="Reasoning", tool_calls=[{"id": "1", "args": {}, "name": "function"}])
        assert raise_memory_updated(message) == message
