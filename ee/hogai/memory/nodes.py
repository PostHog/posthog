from typing import Literal
from uuid import uuid4

from langchain_community.chat_models import ChatPerplexity
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.errors import NodeInterrupt

from ee.hogai.memory.prompts import (
    FAILED_SCRAPING_MESSAGE,
    INITIALIZE_CORE_MEMORY_WITH_BUNDLE_IDS_PROMPT,
    INITIALIZE_CORE_MEMORY_WITH_BUNDLE_IDS_USER_PROMPT,
    INITIALIZE_CORE_MEMORY_WITH_URL_PROMPT,
    INITIALIZE_CORE_MEMORY_WITH_URL_USER_PROMPT,
)
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.nodes import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.models.assistant import CoreMemory
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.schema import (
    AssistantForm,
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
        try:
            core_memory = CoreMemory.objects.get(team=self._team)
        except CoreMemory.DoesNotExist:
            return True
        return not core_memory.is_scraping_pending and not core_memory.is_scraping_finished

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
        return PartialAssistantState(messages=[AssistantMessage(content=answer, id=str(uuid4()))])

    def router(self, state: AssistantState) -> Literal["interrupt", "continue"]:
        last_message = state.messages[-1]
        if isinstance(last_message, AssistantMessage) and last_message.content == FAILED_SCRAPING_MESSAGE:
            return "continue"
        return "interrupt"

    def _model(self):
        return ChatPerplexity(model="llama-3.1-sonar-large-128k-online", streaming=True)


class MemoryInitializerInterruptNode(AssistantNode):
    OPTIONS = ("Yes, save this.", "No, this doesn't look right.")

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        last_message = state.messages[-1]
        if not state.resumed:
            raise NodeInterrupt(
                AssistantMessage(
                    content="Does it look like a good summary of what your product does?",
                    meta=AssistantMessageMetadata(form=AssistantForm(options=self.OPTIONS)),
                    id=str(uuid4()),
                )
            )
        if not isinstance(last_message, HumanMessage):
            raise ValueError("Last messa1ge is not a human message.")
        if last_message.content != self.OPTIONS[0]:
            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content="All right, let's skip this step. You could edit my initial memory in Settings.",
                        id=str(uuid4()),
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
                    content="Thanks! I've updated my initial memory. Let me help with your request.",
                    id=str(uuid4()),
                )
            ]
        )
