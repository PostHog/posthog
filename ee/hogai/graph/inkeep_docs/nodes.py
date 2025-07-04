from typing import Literal
from uuid import uuid4
from django.conf import settings
from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    HumanMessage as LangchainHumanMessage,
    SystemMessage as LangchainSystemMessage,
    BaseMessage,
)
from langchain_core.runnables import RunnableConfig
from .prompts import INKEEP_DATA_CONTINUATION_PHRASE, INKEEP_DOCS_SYSTEM_PROMPT
from ..root.nodes import RootNode
from ee.hogai.utils.state import PartialAssistantState
from ee.hogai.utils.types import AssistantState
from posthog.schema import AssistantMessage, AssistantToolCallMessage
from langchain_core.prompts import ChatPromptTemplate


class InkeepDocsNode(RootNode):  # Inheriting from RootNode to use the same message construction
    """Node for searching PostHog documentation using Inkeep."""

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        """Process the state and return documentation search results."""
        prompt = ChatPromptTemplate(self._construct_messages(state))
        chain = prompt | self._get_model()
        message: LangchainAIMessage = chain.invoke({}, config)
        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content="Checking PostHog documentation...", tool_call_id=state.root_tool_call_id, id=str(uuid4())
                ),
                AssistantMessage(content=message.content, id=str(uuid4())),
            ],
            # Resetting values to empty strings because Nones are not supported by LangGraph.
            root_tool_call_id="",
        )

    def _construct_messages(self, state: AssistantState) -> list[BaseMessage]:
        messages: list[BaseMessage] = [LangchainSystemMessage(content=INKEEP_DOCS_SYSTEM_PROMPT)]
        for message in super()._construct_messages(state):
            if message.content:
                messages.append(message)

        # Only keep the messages up to the last human or system message,
        # as Inkeep doesn't like the last message being an AI one
        last_human_message_index = next(
            (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], LangchainHumanMessage)), None
        )
        if last_human_message_index is not None:
            messages = messages[: last_human_message_index + 1]
        return messages

    def _get_model(self):  # type: ignore
        return ChatOpenAI(
            model="inkeep-qa-sonnet-4",
            base_url="https://api.inkeep.com/v1/",
            api_key=settings.INKEEP_API_KEY,
            streaming=True,
            stream_usage=True,
            max_retries=3,
        )

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
