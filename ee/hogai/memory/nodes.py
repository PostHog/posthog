from typing import Literal
from uuid import uuid4

from langchain_community.chat_models import ChatPerplexity
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.errors import NodeInterrupt

from ee.hogai.memory.prompts import (
    FAILED_SCRAPING_MESSAGE,
    INITIALIZE_CORE_MEMORY_PROMPT_WITH_BUNDLE_IDS,
    INITIALIZE_CORE_MEMORY_PROMPT_WITH_URL,
)
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.nodes import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.models.assistant import CoreMemory
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.schema import AssistantMessage, CachedEventTaxonomyQueryResponse, EventTaxonomyQuery, HumanMessage


class MemoryInitializerNode(AssistantNode):
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        core_memory = CoreMemory.objects.get_or_create(team=self._team)
        retrieved_properties = self._retrieve_context()

        # No host or app bundle ID found, continue.
        if not retrieved_properties or retrieved_properties[0].sample_count == 0:
            core_memory.scraping_status = CoreMemory.ScrapingStatus.SKIPPED
            core_memory.save()
            return PartialAssistantState()

        retrieved_prop = retrieved_properties[0]
        if retrieved_prop.property == "$host":
            prompt = ChatPromptTemplate.from_messages(
                [("human", INITIALIZE_CORE_MEMORY_PROMPT_WITH_URL)], template_format="mustache"
            ).partial(url=retrieved_prop.sample_values[0])
        else:
            prompt = ChatPromptTemplate.from_messages(
                [("human", INITIALIZE_CORE_MEMORY_PROMPT_WITH_BUNDLE_IDS)], template_format="mustache"
            ).partial(bundle_ids=retrieved_prop.sample_values)

        chain = prompt | self._model() | StrOutputParser()
        answer = chain.invoke({}, config=config)

        if "no data available." in answer.lower():
            core_memory.scraping_status = CoreMemory.ScrapingStatus.COMPLETED
            core_memory.save()

            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content=FAILED_SCRAPING_MESSAGE,
                        id=uuid4(),
                    )
                ]
            )

        return PartialAssistantState(messages=[AssistantMessage(content=answer, id=uuid4())])

    def should_run(self, _: AssistantState) -> bool:
        core_memory: CoreMemory | None = self._team.core_memories.first()
        return not core_memory or not core_memory.is_scraping_finished

    def router(self, state: AssistantState) -> Literal["interrupt", "next_node"]:
        last_message = state.messages[-1]
        if (
            isinstance(last_message, HumanMessage)
            or isinstance(last_message, AssistantMessage)
            and last_message.content == FAILED_SCRAPING_MESSAGE
        ):
            return "next_node"
        return "interrupt"

    def _model(self):
        return ChatPerplexity(model="llama-3.1-sonar-huge-128k-online", streaming=True)

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


class MemoryInitializerInterruptNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        last_message = state.messages[-1]
        if isinstance(last_message, AssistantMessage):
            raise NodeInterrupt("Does it look like a good summary of what your product does?")
        if not isinstance(last_message, HumanMessage):
            raise ValueError("Last message is not a human message.")
        if "yes" in last_message.content.lower():
            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content="All right, let's skip this step. You could edit my initial memory in Settings.",
                        id=uuid4(),
                    )
                ]
            )

        core_memory = CoreMemory.objects.get(team=self._team)
        assistant_message = find_last_message_of_type(state.messages, AssistantMessage)

        if not assistant_message:
            raise ValueError("No memory message found.")

        core_memory.set_core_memory(assistant_message.content)
        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content="Thanks! I've updated my initial memory. Let me help with your request.", id=uuid4()
                )
            ]
        )
