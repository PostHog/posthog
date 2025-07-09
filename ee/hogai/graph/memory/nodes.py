import re
from typing import Literal, Optional, Union, cast
from uuid import uuid4

from django.utils import timezone
from langchain_perplexity import ChatPerplexity
from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.output_parsers import PydanticToolsParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.errors import NodeInterrupt
from pydantic import BaseModel, Field, ValidationError

from .parsers import MemoryCollectionCompleted, compressed_memory_parser, raise_memory_updated
from .prompts import (
    ENQUIRY_INITIAL_MESSAGE,
    ONBOARDING_COMPRESSION_PROMPT,
    INITIALIZE_CORE_MEMORY_WITH_BUNDLE_IDS_PROMPT,
    INITIALIZE_CORE_MEMORY_WITH_BUNDLE_IDS_USER_PROMPT,
    INITIALIZE_CORE_MEMORY_WITH_URL_PROMPT,
    INITIALIZE_CORE_MEMORY_WITH_URL_USER_PROMPT,
    MEMORY_COLLECTOR_PROMPT,
    MEMORY_COLLECTOR_WITH_VISUALIZATION_PROMPT,
    MEMORY_ONBOARDING_ENQUIRY_PROMPT,
    ONBOARDING_INITIAL_MESSAGE,
    SCRAPING_CONFIRMATION_MESSAGE,
    SCRAPING_INITIAL_MESSAGE,
    SCRAPING_MEMORY_SAVED_MESSAGE,
    SCRAPING_REJECTION_MESSAGE,
    SCRAPING_SUCCESS_MESSAGE,
    SCRAPING_TERMINATION_MESSAGE,
    SCRAPING_VERIFICATION_MESSAGE,
    TOOL_CALL_ERROR_PROMPT,
)
from ee.hogai.utils.helpers import filter_and_merge_messages, find_last_message_of_type
from ee.hogai.utils.markdown import remove_markdown
from ..base import AssistantNode
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
    VisualizationMessage,
)


class MemoryInitializerContextMixin:
    _team: Team

    def _retrieve_context(self):
        # Retrieve the origin domain.
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


class MemoryOnboardingShouldRunMixin(AssistantNode):
    def should_run_onboarding_at_start(self, state: AssistantState) -> Literal["continue", "memory_onboarding"]:
        """
        If another user has already started the onboarding process, or it has already been completed, do not trigger it again.
        If the conversation starts with the onboarding initial message, start the onboarding process.
        """
        core_memory = self.core_memory

        if core_memory and (core_memory.is_scraping_pending or core_memory.is_scraping_finished):
            # a user has already started the onboarding, we don't allow other users to start it concurrently until timeout is reached
            return "continue"

        last_message = state.messages[-1]
        if isinstance(last_message, HumanMessage) and last_message.content == ONBOARDING_INITIAL_MESSAGE:
            return "memory_onboarding"
        return "continue"


def should_run_onboarding_before_insights(team: Team, state: AssistantState) -> str:
    """
    If another user has already started the onboarding process, or it has already been completed, do not trigger it again.
    Otherwise, start the onboarding process.
    """
    try:
        core_memory = CoreMemory.objects.get(team=team)
    except CoreMemory.DoesNotExist:
        core_memory = None
    if core_memory and (core_memory.is_scraping_pending or core_memory.is_scraping_finished):
        # a user has already started the onboarding, we don't allow other users to start it concurrently until timeout is reached
        return "continue"

    if core_memory is None or core_memory.initial_text == "":
        return "memory_onboarding"
    return "continue"


class MemoryOnboardingNode(MemoryInitializerContextMixin, MemoryOnboardingShouldRunMixin):
    def run(self, state: AssistantState, config: RunnableConfig) -> Optional[PartialAssistantState]:
        core_memory, _ = CoreMemory.objects.get_or_create(team=self._team)
        core_memory.change_status_to_pending()

        # The team has a product description, initialize the memory with it.
        if self._team.project.product_description:
            core_memory.append_question_to_initial_text("What does the company do?")
            core_memory.append_answer_to_initial_text(self._team.project.product_description)
            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content=ENQUIRY_INITIAL_MESSAGE,
                        id=str(uuid4()),
                    )
                ]
            )

        retrieved_properties = self._retrieve_context()

        # No host or app bundle ID found
        if not retrieved_properties or retrieved_properties[0].sample_count == 0:
            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content=ENQUIRY_INITIAL_MESSAGE,
                        id=str(uuid4()),
                    )
                ]
            )

        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content=SCRAPING_INITIAL_MESSAGE,
                    id=str(uuid4()),
                )
            ]
        )

    def router(self, state: AssistantState) -> Literal["initialize_memory", "onboarding_enquiry"]:
        core_memory = self.core_memory
        if core_memory is None or core_memory.initial_text == "":
            return "initialize_memory"
        return "onboarding_enquiry"


class MemoryInitializerNode(MemoryInitializerContextMixin, AssistantNode):
    """
    Scrapes the product description from the given origin or app bundle IDs with Perplexity.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        core_memory, _ = CoreMemory.objects.get_or_create(team=self._team)
        retrieved_properties = self._retrieve_context()
        # No host or app bundle ID found, continue.
        if not retrieved_properties or retrieved_properties[0].sample_count == 0:
            return PartialAssistantState(messages=[])

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
            return PartialAssistantState(
                messages=[AssistantMessage(content=SCRAPING_TERMINATION_MESSAGE, id=str(uuid4()))]
            )

        # Otherwise, proceed to confirmation that the memory is correct.
        core_memory.append_question_to_initial_text("What does the company do?")
        core_memory.append_answer_to_initial_text(answer)
        return PartialAssistantState(messages=[AssistantMessage(content=self.format_message(answer), id=str(uuid4()))])

    def router(self, state: AssistantState) -> Literal["interrupt", "continue"]:
        last_message = state.messages[-1]
        if (
            isinstance(last_message, AssistantMessage)
            and SCRAPING_SUCCESS_MESSAGE.lower() in last_message.content.lower()
        ):
            return "interrupt"
        return "continue"

    @classmethod
    def should_process_message_chunk(cls, message: AIMessageChunk) -> bool:
        placeholder = "no data available"
        content = cast(str, message.content)
        return placeholder not in content.lower() and len(content) > len(placeholder)

    @classmethod
    def format_message(cls, message: str) -> str:
        return SCRAPING_SUCCESS_MESSAGE + re.sub(r"\[\d+\]", "", message)

    def _model(self):
        return ChatPerplexity(model="sonar-pro", temperature=0.3, streaming=True, timeout=60)


class MemoryInitializerInterruptNode(AssistantNode):
    """
    Prompts the user to confirm or reject the scraped memory. Since Perplexity doesn't guarantee the quality of the scraped data, we need to verify it with the user.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        raise NodeInterrupt(
            AssistantMessage(
                content=SCRAPING_VERIFICATION_MESSAGE,
                meta=AssistantMessageMetadata(
                    form=AssistantForm(
                        options=[
                            AssistantFormOption(value=SCRAPING_CONFIRMATION_MESSAGE, variant="primary"),
                            AssistantFormOption(value=SCRAPING_REJECTION_MESSAGE),
                        ]
                    )
                ),
                id=str(uuid4()),
            )
        )


class MemoryOnboardingEnquiryNode(AssistantNode):
    """
    Prompts the user to give more information about the product, feature, business, etc.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        human_message = find_last_message_of_type(state.messages, HumanMessage)
        if not human_message:
            raise ValueError("No human message found.")

        core_memory, _ = CoreMemory.objects.get_or_create(team=self._team)
        if human_message.content not in [
            SCRAPING_CONFIRMATION_MESSAGE,
            SCRAPING_REJECTION_MESSAGE,
            ONBOARDING_INITIAL_MESSAGE,
        ] and core_memory.initial_text.endswith("Answer:"):
            # The user is answering to a question
            core_memory.append_answer_to_initial_text(human_message.content)

        if human_message.content == SCRAPING_REJECTION_MESSAGE:
            core_memory.initial_text = ""
            core_memory.save()

        answers_left = core_memory.answers_left
        if answers_left > 0:
            prompt = ChatPromptTemplate.from_messages(
                [("system", MEMORY_ONBOARDING_ENQUIRY_PROMPT)], template_format="mustache"
            ).partial(core_memory=core_memory.initial_text, questions_left=answers_left)

            chain = prompt | self._model | StrOutputParser()
            response = chain.invoke({}, config=config)

            if "[Done]" not in response and "===" in response:
                question = self._format_question(response)
                core_memory.append_question_to_initial_text(question)
                return PartialAssistantState(onboarding_question=question)
        return PartialAssistantState(onboarding_question="")

    @property
    def _model(self):
        return ChatOpenAI(
            model="gpt-4.1", temperature=0.3, disable_streaming=True, stop_sequences=["[Done]"], max_retries=3
        )

    def router(self, state: AssistantState) -> Literal["continue", "interrupt"]:
        core_memory = self.core_memory
        if core_memory is None:
            raise ValueError("No core memory found.")
        if state.onboarding_question and core_memory.answers_left > 0:
            return "interrupt"
        return "continue"

    def _format_memory(self, memory: str) -> str:
        """
        Remove markdown and source reference tags like [1], [2], etc.
        """
        return remove_markdown(memory)

    def _format_question(self, question: str) -> str:
        if "===" in question:
            question = question.split("===")[1]
        return remove_markdown(question)


class MemoryOnboardingEnquiryInterruptNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        last_assistant_message = find_last_message_of_type(state.messages, AssistantMessage)
        if not state.onboarding_question:
            raise ValueError("No onboarding question found.")
        if last_assistant_message and last_assistant_message.content != state.onboarding_question:
            raise NodeInterrupt(AssistantMessage(content=state.onboarding_question, id=str(uuid4())))
        return PartialAssistantState(messages=[], onboarding_question="")


class MemoryOnboardingFinalizeNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        core_memory = self.core_memory
        if core_memory is None:
            raise ValueError("No core memory found.")
        # Compress the question/answer memory before saving it
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", ONBOARDING_COMPRESSION_PROMPT),
                ("human", core_memory.initial_text),
            ]
        )
        chain = prompt | self._model | StrOutputParser() | compressed_memory_parser
        compressed_memory = cast(str, chain.invoke({}, config=config))
        compressed_memory = compressed_memory.replace("\n", " ").strip()
        core_memory.set_core_memory(compressed_memory)
        return PartialAssistantState(
            messages=[AssistantMessage(content=SCRAPING_MEMORY_SAVED_MESSAGE, id=str(uuid4()))]
        )

    @property
    def _model(self):
        return ChatOpenAI(
            model="gpt-4.1", temperature=0.3, disable_streaming=True, stop_sequences=["[Done]"], max_retries=3
        )

    def router(self, state: AssistantState) -> Literal["continue", "insights"]:
        core_memory = self.core_memory
        if core_memory is None:
            raise ValueError("No core memory found.")
        if state.root_tool_insight_plan:
            return "insights"
        return "continue"


# Lower casing matters here. Do not change it.
class core_memory_append(BaseModel):
    """
    Appends a new memory fragment to persistent storage.
    """

    memory_content: str = Field(description="The content of a new memory to be added to storage.")


# Lower casing matters here. Do not change it.
class core_memory_replace(BaseModel):
    """
    Replaces a specific fragment of memory (word, sentence, paragraph, etc.) with another in persistent storage.
    """

    original_fragment: str = Field(description="The content of the memory to be replaced.")
    new_fragment: str = Field(description="The content to replace the existing memory with.")


memory_collector_tools = [core_memory_append, core_memory_replace]


class MemoryCollectorNode(MemoryOnboardingShouldRunMixin):
    """
    The Memory Collector manages the core memory of the agent. Core memory is a text containing facts about a user's company and product. It helps the agent save and remember facts that could be useful for insight generation or other agentic functions requiring deeper context about the product.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        if self.should_run_onboarding_at_start(state) != "continue":
            return None

        node_messages = state.memory_collection_messages or []

        prompt = ChatPromptTemplate.from_messages(
            [("system", MEMORY_COLLECTOR_PROMPT)], template_format="mustache"
        ) + self._construct_messages(state)
        chain = prompt | self._model | raise_memory_updated

        try:
            response = chain.invoke(
                {
                    "core_memory": self.core_memory_text,
                    "date": timezone.now().strftime("%Y-%m-%d"),
                },
                config=config,
            )
        except MemoryCollectionCompleted:
            return PartialAssistantState(memory_updated=len(node_messages) > 0, memory_collection_messages=[])
        return PartialAssistantState(memory_collection_messages=[*node_messages, cast(LangchainAIMessage, response)])

    def router(self, state: AssistantState) -> Literal["tools", "next"]:
        if not state.memory_collection_messages:
            return "next"
        return "tools"

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4o", temperature=0.3, disable_streaming=True, max_retries=3).bind_tools(
            memory_collector_tools
        )

    def _construct_messages(self, state: AssistantState) -> list[BaseMessage]:
        node_messages = state.memory_collection_messages or []

        filtered_messages = filter_and_merge_messages(
            state.messages, entity_filter=(HumanMessage, AssistantMessage, VisualizationMessage)
        )
        conversation: list[BaseMessage] = []

        for message in filtered_messages:
            if isinstance(message, HumanMessage):
                conversation.append(LangchainHumanMessage(content=message.content, id=message.id))
            elif isinstance(message, AssistantMessage):
                conversation.append(LangchainAIMessage(content=message.content, id=message.id))
            elif isinstance(message, VisualizationMessage) and message.answer:
                conversation += ChatPromptTemplate.from_messages(
                    [
                        ("assistant", MEMORY_COLLECTOR_WITH_VISUALIZATION_PROMPT),
                    ],
                    template_format="mustache",
                ).format_messages(
                    schema=message.answer.model_dump_json(exclude_unset=True, exclude_none=True),
                )

        # Trim messages to keep only last 10 messages.
        messages = [*conversation[-10:], *node_messages]
        return messages


class MemoryCollectorToolsNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        node_messages = state.memory_collection_messages
        if not node_messages:
            raise ValueError("No memory collection messages found.")
        last_message = node_messages[-1]
        if not isinstance(last_message, LangchainAIMessage):
            raise ValueError("Last message must be an AI message.")
        core_memory = self.core_memory
        if core_memory is None:
            raise ValueError("No core memory found.")

        tools_parser = PydanticToolsParser(tools=memory_collector_tools)
        try:
            tool_calls: list[Union[core_memory_append, core_memory_replace]] = tools_parser.invoke(
                last_message, config=config
            )
        except ValidationError as e:
            failover_messages = ChatPromptTemplate.from_messages(
                [("user", TOOL_CALL_ERROR_PROMPT)], template_format="mustache"
            ).format_messages(validation_error_message=e.errors(include_url=False))
            return PartialAssistantState(
                memory_collection_messages=[*node_messages, *failover_messages],
            )

        new_messages: list[LangchainToolMessage] = []
        for tool_call, schema in zip(last_message.tool_calls, tool_calls):
            if isinstance(schema, core_memory_append):
                core_memory.append_core_memory(schema.memory_content)
                new_messages.append(LangchainToolMessage(content="Memory appended.", tool_call_id=tool_call["id"]))
            if isinstance(schema, core_memory_replace):
                try:
                    core_memory.replace_core_memory(schema.original_fragment, schema.new_fragment)
                    new_messages.append(LangchainToolMessage(content="Memory replaced.", tool_call_id=tool_call["id"]))
                except ValueError as e:
                    new_messages.append(LangchainToolMessage(content=str(e), tool_call_id=tool_call["id"]))

        return PartialAssistantState(
            memory_collection_messages=[*node_messages, *new_messages],
        )
