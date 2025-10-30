from collections.abc import Mapping, Sequence
from typing import Any, Literal
from uuid import uuid4

from django.conf import settings

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
    SystemMessage as LangchainSystemMessage,
)
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, AssistantToolCallMessage, FailureMessage

from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.utils.openai import convert_to_openai_messages
from ee.hogai.utils.state import PartialAssistantState
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import AssistantMessageUnion, AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName

from ..root.nodes import RootNode
from .prompts import INKEEP_DATA_CONTINUATION_PHRASE, INKEEP_DOCS_SYSTEM_PROMPT


class InkeepDocsNode(RootNode):  # Inheriting from RootNode to use the same message construction
    """Node for searching PostHog documentation using Inkeep."""

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.INKEEP_DOCS

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        """Process the state and return documentation search results."""
        self.dispatcher.message(AssistantMessage(content="Checking PostHog documentation...", id=str(uuid4())))
        messages = self._construct_messages(
            state.messages, state.root_conversation_start_id, state.root_tool_calls_count
        )
        message: LangchainAIMessage = await self._get_model().ainvoke(messages, config)
        # NOTE: This is a hacky way to send these messages as part of the root tool call
        # Can't think of a better interface for this at the moment.
        self.dispatcher.set_as_root()
        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content="Checking PostHog documentation...", tool_call_id=state.root_tool_call_id, id=str(uuid4())
                ),
                AssistantMessage(content=message.content, id=str(uuid4())),
            ],
            root_tool_call_id=None,
        )

    def _construct_messages(
        self,
        messages: Sequence[AssistantMessageUnion],
        window_start_id: str | None = None,
        tool_calls_count: int | None = None,
    ) -> list[BaseMessage]:
        conversation_window = self._window_manager.get_messages_in_window(messages, window_start_id)
        # Inkeep supports maximum 30 messages. Two are reserved for system prompts.
        conversation_window = conversation_window[-28:]
        langchain_messages = self._convert_to_langchain_messages(
            conversation_window, self._get_tool_map(conversation_window)
        )

        # Inkeep doesn't support AIMessages without content.
        # Add some content that won't reflect in the final response.
        for msg in langchain_messages:
            if isinstance(msg, LangchainAIMessage) and not msg.content:
                msg.content = "..."  # Patch until Inkeep supports empty AI messages

        # Only keep the messages up to the last human or system message,
        # as Inkeep doesn't like the last message being an AI one
        last_human_message_index = next(
            (
                i
                for i in range(len(langchain_messages) - 1, -1, -1)
                if isinstance(langchain_messages[i], LangchainHumanMessage)
            ),
            None,
        )
        if last_human_message_index is not None:
            langchain_messages = langchain_messages[: last_human_message_index + 1]

        return [LangchainSystemMessage(content=INKEEP_DOCS_SYSTEM_PROMPT), *langchain_messages]

    def _get_model(self, *args, **kwargs):
        return MaxChatOpenAI(
            model="inkeep-qa-expert",
            base_url="https://api.inkeep.com/v1/",
            api_key=settings.INKEEP_API_KEY,
            streaming=True,
            stream_usage=True,
            user=self._user,
            team=self._team,
        )

    async def _has_reached_token_limit(self, model: Any, window: list[BaseMessage]) -> bool:
        # The root node on this step will always have the correct window.
        return False

    def _filter_assistant_messages(self, messages: Sequence[AssistantMessageUnion]):
        """Filter out messages that are not part of the assistant conversation."""
        return [
            message
            for message in super()._filter_assistant_messages(messages)
            if not isinstance(message, FailureMessage)
        ]

    def _convert_to_langchain_messages(
        self,
        conversation_window: Sequence[AssistantMessageUnion],
        tool_result_messages: Mapping[str, AssistantToolCallMessage],
    ) -> list[BaseMessage]:
        # Original node has Anthropic messages, but Inkeep expects OpenAI messages
        return convert_to_openai_messages(conversation_window, tool_result_messages)

    def router(self, state: AssistantState) -> Literal["end", "root"]:
        last_message = state.messages[-1]
        if isinstance(last_message, AssistantMessage) and INKEEP_DATA_CONTINUATION_PHRASE in last_message.content:
            # The continuation phrase solution is a little weird, but seems it's the best one for agentic capabilities
            # I've found here. The alternatives that definitively don't work are:
            # 1. Using tool calls in this node - the Inkeep API only supports providing their own pre-defined tools
            #    (for including extra search metadata), nothing else
            # 2. Always going back to root, for root to judge whether to continue or not - GPT-4o is terrible at this,
            #    and I was unable to stop it from repeating the context from the last assistant message, i.e. the Inkeep
            #    output message (doesn't quite work to tell it to output an empty message, or to call an "end" tool)
            return "root"
        return "end"
