from collections.abc import Sequence

from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from pydantic import Field


class TokenCounterMixin:
    openai_model: str

    def get_num_tokens_from_messages(self, messages: list[BaseMessage], tools: Sequence | None = None) -> int:
        chat = ChatOpenAI(model=self.openai_model, api_key="no-key")
        return chat.get_num_tokens_from_messages(messages, tools)


class FakeChatOpenAI(TokenCounterMixin, FakeMessagesListChatModel):
    openai_model: str = Field(default="gpt-4o")

    def invoke(self, input, config=None, **kwargs):
        result = super().invoke(input, config, **kwargs)
        # Add response metadata with an ID to match behavior of ChatOpenAI with the Responses API
        if not hasattr(result, "response_metadata") or result.response_metadata is None:
            result.response_metadata = {"id": "fake_response_id"}
        elif "id" not in result.response_metadata:
            result.response_metadata["id"] = "fake_response_id"
        return result


class FakeRunnableLambdaWithTokenCounter(TokenCounterMixin, RunnableLambda):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.openai_model = kwargs.get("openai_model", "gpt-4o")
