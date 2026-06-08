from posthog.test.base import BaseTest

from langchain_core.messages import AIMessage

from ee.hogai.chat_agent.memory.parsers import check_memory_collection_completed, compressed_memory_parser


class TestParsers(BaseTest):
    def test_compressed_memory_parser(self):
        memory = "Hello\n\nWorld "
        assert compressed_memory_parser(memory) == "Hello\nWorld "

    def test_check_memory_collection_completed(self):
        message = AIMessage(content="Hello World")
        assert check_memory_collection_completed(message) is None

        message = AIMessage(content="[Done]", tool_calls=[{"id": "1", "args": {}, "name": "function"}])
        assert check_memory_collection_completed(message) is None

        message = AIMessage(content="Reasoning", tool_calls=[{"id": "1", "args": {}, "name": "function"}])
        assert check_memory_collection_completed(message) == message
