from posthog.test.base import BaseTest

from langchain_core.messages import AIMessage

from ee.hogai.chat_agent.memory.parsers import check_memory_collection_completed, compressed_memory_parser


class TestParsers(BaseTest):
    def test_compressed_memory_parser(self):
        memory = "Hello\n\nWorld "
        self.assertEqual(compressed_memory_parser(memory), "Hello\nWorld ")

    def test_check_memory_collection_completed(self):
        message = AIMessage(content="Hello World")
        self.assertIsNone(check_memory_collection_completed(message))

        message = AIMessage(content="[Done]", tool_calls=[{"id": "1", "args": {}, "name": "function"}])
        self.assertIsNone(check_memory_collection_completed(message))

        message = AIMessage(content="Reasoning", tool_calls=[{"id": "1", "args": {}, "name": "function"}])
        self.assertEqual(check_memory_collection_completed(message), message)
