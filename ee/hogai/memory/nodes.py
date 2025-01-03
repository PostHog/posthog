import re
from typing import Literal, cast
from uuid import uuid4

from langchain_community.chat_models import ChatPerplexity
from langchain_core.messages import AIMessageChunk
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.errors import NodeInterrupt

from ee.hogai.memory.parsers import compressed_memory_parser
from ee.hogai.memory.prompts import (
    COMPRESSION_PROMPT,
    FAILED_SCRAPING_MESSAGE,
    INITIALIZE_CORE_MEMORY_WITH_BUNDLE_IDS_PROMPT,
    INITIALIZE_CORE_MEMORY_WITH_BUNDLE_IDS_USER_PROMPT,
    INITIALIZE_CORE_MEMORY_WITH_URL_PROMPT,
    INITIALIZE_CORE_MEMORY_WITH_URL_USER_PROMPT,
)
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.markdown import remove_markdown
from ee.hogai.utils.nodes import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.models.assistant import CoreMemory
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.schema import (
    AssistantForm,
    AssistantFormOption,
    AssistantMessage,
    AssistantMessageMetadata,
    CachedEventTaxonomyQueryResponse,
    EventTaxonomyQuery,
    HumanMessage,
)


class MemoryInitializerContextMixin:
    _team: Team

    def _retrieve_context(self):
        # Retrieve the origin URL.
        runner = EventTaxonomyQueryRunner(
            team=self._team, query=EventTaxonomyQuery(event="$pageview", properties=["$host"])
        )
        response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS)
        if not isinstance(response, CachedEventTaxonomyQueryResponse):
            raise ValueError("Failed to query the event taxonomy.")
        # Otherwise, retrieve the app bundle ID.
        if not response.results:
            runner = EventTaxonomyQueryRunner(
                team=self._team, query=EventTaxonomyQuery(event="$screen", properties=["$app_namespace"])
            )
            response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS)
        if not isinstance(response, CachedEventTaxonomyQueryResponse):
            raise ValueError("Failed to query the event taxonomy.")
        return response.results


class MemoryOnboardingNode(MemoryInitializerContextMixin, AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        core_memory, _ = CoreMemory.objects.get_or_create(team=self._team)
        retrieved_properties = self._retrieve_context()

        # No host or app bundle ID found, continue.
        if not retrieved_properties or retrieved_properties[0].sample_count == 0:
            core_memory.change_status_to_skipped()
            return PartialAssistantState()

        core_memory.change_status_to_pending()
        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content="Hey, my name is Max. Before we start, let's find and verify information about your product.",
                    id=str(uuid4()),
                )
            ]
        )

    def should_run(self, _: AssistantState) -> bool:
        core_memory = self.core_memory
        return not core_memory or (not core_memory.is_scraping_pending and not core_memory.is_scraping_finished)

    def router(self, state: AssistantState) -> Literal["initialize_memory", "continue"]:
        last_message = state.messages[-1]
        if isinstance(last_message, HumanMessage):
            return "continue"
        return "initialize_memory"


class MemoryInitializerNode(MemoryInitializerContextMixin, AssistantNode):
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        core_memory, _ = CoreMemory.objects.get_or_create(team=self._team)
        retrieved_properties = self._retrieve_context()

        # No host or app bundle ID found, continue.
        if not retrieved_properties or retrieved_properties[0].sample_count == 0:
            raise ValueError("No host or app bundle ID found in the memory initializer.")

        retrieved_prop = retrieved_properties[0]
        if retrieved_prop.property == "$host":
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", INITIALIZE_CORE_MEMORY_WITH_URL_PROMPT),
                    ("human", INITIALIZE_CORE_MEMORY_WITH_URL_USER_PROMPT),
                ],
                template_format="mustache",
            ).partial(url=retrieved_prop.sample_values[0])
        else:
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", INITIALIZE_CORE_MEMORY_WITH_BUNDLE_IDS_PROMPT),
                    ("human", INITIALIZE_CORE_MEMORY_WITH_BUNDLE_IDS_USER_PROMPT),
                ],
                template_format="mustache",
            ).partial(bundle_ids=retrieved_prop.sample_values)

        chain = prompt | self._model() | StrOutputParser()
        answer = chain.invoke({}, config=config)

        # Perplexity has failed to scrape the data, continue.
        if "no data available." in answer.lower():
            core_memory.change_status_to_skipped()
            return PartialAssistantState(messages=[AssistantMessage(content=FAILED_SCRAPING_MESSAGE, id=str(uuid4()))])
        return PartialAssistantState(messages=[AssistantMessage(content=self.format_message(answer), id=str(uuid4()))])

    def router(self, state: AssistantState) -> Literal["interrupt", "continue"]:
        last_message = state.messages[-1]
        if isinstance(last_message, AssistantMessage) and last_message.content == FAILED_SCRAPING_MESSAGE:
            return "continue"
        return "interrupt"

    @classmethod
    def should_process_message_chunk(cls, message: AIMessageChunk) -> bool:
        placeholder = "no data available"
        content = cast(str, message.content)
        return placeholder not in content.lower() and len(content) > len(placeholder)

    @classmethod
    def format_message(cls, message: str) -> str:
        return re.sub(r"\[\d+\]", "", message)

    def _model(self):
        return ChatPerplexity(model="llama-3.1-sonar-large-128k-online", temperature=0, streaming=True)


class MemoryInitializerInterruptNode(AssistantNode):
    OPTIONS = ("Yes, save this.", "No, this doesn't look right.")

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        last_message = state.messages[-1]
        if not state.resumed:
            raise NodeInterrupt(
                AssistantMessage(
                    content="Does it look like a good summary of what your product does?",
                    meta=AssistantMessageMetadata(
                        form=AssistantForm(
                            options=[
                                AssistantFormOption(value=self.OPTIONS[0], variant="primary"),
                                AssistantFormOption(value=self.OPTIONS[1]),
                            ]
                        )
                    ),
                    id=str(uuid4()),
                )
            )
        if not isinstance(last_message, HumanMessage):
            raise ValueError("Last message is not a human message.")
        if last_message.content != self.OPTIONS[0]:
            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content="All right, let's skip this step. You could edit my initial memory in Settings.",
                        id=str(uuid4()),
                    )
                ]
            )

        core_memory = self.core_memory
        if not core_memory:
            raise ValueError("No core memory found.")

        assistant_message = find_last_message_of_type(state.messages, AssistantMessage)

        if not assistant_message:
            raise ValueError("No memory message found.")

        # Compress the memory before saving it. It removes unneeded redundancy.
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", COMPRESSION_PROMPT),
                ("human", self._format_memory(assistant_message.content)),
            ]
        )
        chain = prompt | self._model | StrOutputParser() | compressed_memory_parser
        compressed_memory = cast(str, chain.invoke({}, config=config))
        core_memory.set_core_memory(compressed_memory)

        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content="Thanks! I've updated my initial memory. Let me help with your request.",
                    id=str(uuid4()),
                )
            ]
        )

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4o-mini", temperature=0)

    def _format_memory(self, memory: str) -> str:
        """
        Remove markdown and source reference tags like [1], [2], etc.
        """
        return remove_markdown(memory)
