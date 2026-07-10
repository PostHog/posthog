from collections.abc import Sequence
from contextlib import contextmanager

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import BaseMessage, convert_to_messages, convert_to_openai_messages
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from pydantic import Field


@contextmanager
def mock_contextual_tool(mock_tool):
    """Helper to mock a contextual tool class with create_tool_class"""
    mock_tool_class = MagicMock()
    mock_tool_class.create_tool_class = AsyncMock(return_value=mock_tool)

    # toolkit.py imports get_contextual_tool_class by value at module level,
    # so it must be patched there too, not just on the registry module
    with (
        patch("ee.hogai.registry.get_contextual_tool_class", return_value=mock_tool_class),
        patch("ee.hogai.chat_agent.toolkit.get_contextual_tool_class", return_value=mock_tool_class),
    ):
        yield


class TokenCounterMixin:
    model: str

    def get_num_tokens_from_messages(
        self, messages: list[BaseMessage], *args, tools: Sequence | None = None, **kwargs
    ) -> int:
        chat = ChatOpenAI(model=self.model, api_key="no-key")
        count = chat.get_num_tokens_from_messages(messages, tools)
        return count


class FakeChatOpenAI(TokenCounterMixin, FakeMessagesListChatModel):
    model: str = Field(default="gpt-4o")

    def invoke(self, input, config=None, **kwargs):
        result = super().invoke(input, config, **kwargs)
        # Add response metadata with an ID to match behavior of ChatOpenAI with the Responses API
        if not hasattr(result, "response_metadata") or result.response_metadata is None:
            result.response_metadata = {"id": "fake_response_id"}
        elif "id" not in result.response_metadata:
            result.response_metadata["id"] = "fake_response_id"
        return result


class AnthropicTokenCounterMixin(TokenCounterMixin):
    def get_num_tokens_from_messages(
        self, messages: list[BaseMessage], *args, tools: Sequence | None = None, **kwargs
    ) -> int:
        content = convert_to_messages(convert_to_openai_messages(messages))
        return super().get_num_tokens_from_messages(content, tools)


class FakeChatAnthropic(AnthropicTokenCounterMixin, FakeMessagesListChatModel):
    model: str = (
        "gpt-4o"  # Do not change `gpt-4o`. Emulate the token counter since the actual token counter is a HTTP request.
    )


class FakeOpenAIRunnableLambdaWithTokenCounter(TokenCounterMixin, RunnableLambda):
    model: str = "gpt-4o"


class FakeAnthropicRunnableLambdaWithTokenCounter(AnthropicTokenCounterMixin, RunnableLambda):
    model: str = (
        "gpt-4o"  # Do not change `gpt-4o`. Emulate the token counter since the actual token counter is a HTTP request.
    )
