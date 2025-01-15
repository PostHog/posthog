from langchain_core.messages import AIMessage

from ee.hogai.memory.parsers import MemoryCollectionCompleted, compressed_memory_parser, raise_memory_updated
from posthog.test.base import BaseTest


class TestParsers(BaseTest):
    def test_compressed_memory_parser(self):
        memory = "Hello\n\nWorld "
        self.assertEqual(compressed_memory_parser(memory), "Hello\nWorld ")

    def test_raise_memory_updated(self):
        message = AIMessage(content="Hello World")
        with self.assertRaises(MemoryCollectionCompleted):
            raise_memory_updated(message)

        message = AIMessage(content="[Done]", tool_calls=[{"id": "1", "args": {}, "name": "function"}])
        with self.assertRaises(MemoryCollectionCompleted):
            raise_memory_updated(message)

        message = AIMessage(content="Reasoning", tool_calls=[{"id": "1", "args": {}, "name": "function"}])
        self.assertEqual(raise_memory_updated(message), message)
