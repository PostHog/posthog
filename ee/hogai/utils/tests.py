from collections.abc import Sequence

from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import BaseMessage, convert_to_messages, convert_to_openai_messages
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from pydantic import Field


class TokenCounterMixin:
    model: str

    def get_num_tokens_from_messages(
        self, messages: list[BaseMessage], *args, tools: Sequence | None = None, **kwargs
    ) -> int:
        chat = ChatOpenAI(model=self.model, api_key="no-key")
        return chat.get_num_tokens_from_messages(messages, tools)


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


class FakeChatAnthropic(TokenCounterMixin, FakeMessagesListChatModel):
    # Emulate the token counter since the actual token counter is a HTTP request.
    model: str = "gpt-4o"

    def get_num_tokens_from_messages(
        self, messages: list[BaseMessage], *args, tools: Sequence | None = None, **kwargs
    ) -> int:
        content = convert_to_messages(convert_to_openai_messages(messages))
        return super().get_num_tokens_from_messages(content, tools)


class FakeRunnableLambdaWithTokenCounter(TokenCounterMixin, RunnableLambda):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model = kwargs.get("model", "gpt-4o")
