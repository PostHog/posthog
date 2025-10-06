from typing import Literal, Optional, Union, cast
from uuid import uuid4

from django.utils import timezone

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.output_parsers import PydanticToolsParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.errors import NodeInterrupt
from pydantic import BaseModel, Field, ValidationError

from posthog.schema import (
    AssistantForm,
    AssistantFormOption,
    AssistantMessage,
    AssistantMessageMetadata,
    CachedEventTaxonomyQueryResponse,
    EventTaxonomyItem,
    EventTaxonomyQuery,
    HumanMessage,
    VisualizationMessage,
)

from posthog.event_usage import report_user_action
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.utils import human_list

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.mixins import AssistantContextMixin
from ee.hogai.graph.root.nodes import SLASH_COMMAND_INIT, SLASH_COMMAND_REMEMBER
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.utils.helpers import filter_and_merge_messages, find_last_message_of_type
from ee.hogai.utils.markdown import remove_markdown
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName
from ee.models.assistant import CoreMemory

from .parsers import MemoryCollectionCompleted, compressed_memory_parser, raise_memory_updated
from .prompts import (
    ENQUIRY_INITIAL_MESSAGE,
    INITIALIZE_CORE_MEMORY_SYSTEM_PROMPT,
    INITIALIZE_CORE_MEMORY_WITH_BUNDLE_IDS_USER_PROMPT,
    INITIALIZE_CORE_MEMORY_WITH_DOMAINS_USER_PROMPT,
    MEMORY_COLLECTOR_PROMPT,
    MEMORY_COLLECTOR_WITH_VISUALIZATION_PROMPT,
    MEMORY_ONBOARDING_ENQUIRY_PROMPT,
    ONBOARDING_COMPRESSION_PROMPT,
    SCRAPING_CONFIRMATION_MESSAGE,
    SCRAPING_INITIAL_MESSAGE,
    SCRAPING_MEMORY_SAVED_MESSAGE,
    SCRAPING_REJECTION_MESSAGE,
    SCRAPING_SUCCESS_KEY_PHRASE,
    SCRAPING_TERMINATION_MESSAGE,
    SCRAPING_VERIFICATION_MESSAGE,
    TOOL_CALL_ERROR_PROMPT,
)


class MemoryInitializerContextMixin(AssistantContextMixin):
    def _retrieve_context(self, *, config: RunnableConfig | None = None) -> EventTaxonomyItem | None:
        if config and "_mock_memory_onboarding_context" in config.get("configurable", {}):
            # Only for evals/tests (as patch() doesn't work because of evals running concurrently async)
            return config["configurable"]["_mock_memory_onboarding_context"]
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
        if not response.results:
            return None
        item = response.results[0]
        # Exclude localhost from sample values. We could maybe do it at the query level.
        # Note: This means if there are $host values but only localhost, we will miss out on any potential $app_namespace values
        # This is probably okay - it's just simpler code-wise here
        item.sample_values = [
            v
            for v in item.sample_values
            if v != "localhost" and not v.startswith("localhost:") and not v.startswith("127.0.0.1")
        ]
        if not item.sample_values:
            return None
        return item


class MemoryOnboardingShouldRunMixin(AssistantNode):
    def should_run_onboarding_at_start(self, state: AssistantState) -> Literal["continue", "memory_onboarding"]:
        """
        Only trigger memory onboarding when explicitly requested with /init command.
        If another user has already started the onboarding process, or it has already been completed, do not trigger it again.
        If no messages are to be found in the AssistantState, do not run onboarding.
        """
        core_memory = self.core_memory

        if core_memory and core_memory.is_scraping_pending:
            # a user has already started the onboarding, we don't allow other users to start it concurrently until timeout is reached
            return "continue"

        if not state.messages:
            return "continue"

        last_message = state.messages[-1]
        if isinstance(last_message, HumanMessage) and last_message.content.startswith("/"):
            report_user_action(
                self._user, "Max slash command used", {"slash_command": last_message.content}, team=self._team
            )
        if isinstance(last_message, HumanMessage) and last_message.content == SLASH_COMMAND_INIT:
            return "memory_onboarding"
        return "continue"


class MemoryOnboardingNode(MemoryInitializerContextMixin, MemoryOnboardingShouldRunMixin):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.MEMORY_ONBOARDING

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

        retrieved_prop = self._retrieve_context(config=config)

        # No host or app bundle ID found
        if not retrieved_prop:
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
                    content=SCRAPING_INITIAL_MESSAGE.format(
                        domains_or_bundle_ids_formatted=human_list([f"`{x}`" for x in retrieved_prop.sample_values])
                    ),
                    id=str(uuid4()),
                )
            ]
        )


class MemoryInitializerNode(MemoryInitializerContextMixin, AssistantNode):
    """
    Scrapes the product description from the given origin or app bundle IDs.
    """

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.MEMORY_INITIALIZER

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        core_memory, _ = CoreMemory.objects.get_or_create(team=self._team)
        if core_memory.initial_text:
            # Reset the initial text if it's not the first time /init is ran
            core_memory.initial_text = ""
            core_memory.save()
        retrieved_prop = self._retrieve_context(config=config)
        # No host or app bundle ID found, continue.
        if not retrieved_prop:
            return None

        prompt = ChatPromptTemplate.from_messages(
            [("system", INITIALIZE_CORE_MEMORY_SYSTEM_PROMPT)], template_format="mustache"
        )
        if retrieved_prop.property == "$host":
            prompt += ChatPromptTemplate.from_messages(
                [("human", INITIALIZE_CORE_MEMORY_WITH_DOMAINS_USER_PROMPT)], template_format="mustache"
            ).partial(domains=",".join(retrieved_prop.sample_values))
        else:
            prompt += ChatPromptTemplate.from_messages(
                [("human", INITIALIZE_CORE_MEMORY_WITH_BUNDLE_IDS_USER_PROMPT)], template_format="mustache"
            ).partial(bundle_ids=",".join(retrieved_prop.sample_values))

        chain = prompt | self._model() | StrOutputParser()
        answer = chain.invoke({}, config=config)
        # The model has failed to scrape the data, continue.
        if answer == SCRAPING_TERMINATION_MESSAGE:
            return PartialAssistantState(messages=[AssistantMessage(content=answer, id=str(uuid4()))])
        # Otherwise, proceed to confirmation that the memory is correct.
        core_memory.append_question_to_initial_text("What does the company do?")
        core_memory.append_answer_to_initial_text(answer)
        return PartialAssistantState(messages=[AssistantMessage(content=answer, id=str(uuid4()))])

    def router(self, state: AssistantState) -> Literal["interrupt", "continue"]:
        last_message = state.messages[-1]
        if isinstance(last_message, AssistantMessage) and SCRAPING_SUCCESS_KEY_PHRASE in last_message.content:
            return "interrupt"
        return "continue"

    def _model(self):
        return MaxChatOpenAI(
            model="gpt-5-mini",
            streaming=True,
            use_responses_api=True,
            store=False,  # We can't store, because we want zero data retention
            reasoning={
                "summary": "auto",  # Without this, there's no reasoning summaries! Only works with reasoning models
            },
            user=self._user,
            team=self._team,
        ).bind_tools([{"type": "web_search_preview"}])  # We should use web_search once LangChain supports it


class MemoryInitializerInterruptNode(AssistantNode):
    """
    Prompts the user to confirm or reject the scraped memory.
    """

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.MEMORY_INITIALIZER_INTERRUPT

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

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        human_message = find_last_message_of_type(state.messages, HumanMessage)
        if not human_message:
            raise ValueError("No human message found.")

        core_memory, _ = CoreMemory.objects.get_or_create(team=self._team)
        if (
            human_message.content not in [SCRAPING_CONFIRMATION_MESSAGE, SCRAPING_REJECTION_MESSAGE]
            and not human_message.content.startswith("/")  # Ignore slash commands
            and core_memory.initial_text.endswith("Answer:")
        ):
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
        return PartialAssistantState(onboarding_question=None)

    @property
    def _model(self):
        return MaxChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
            disable_streaming=True,
            stop_sequences=["[Done]"],
            user=self._user,
            team=self._team,
        )

    def router(self, state: AssistantState) -> Literal["continue", "interrupt"]:
        core_memory, _ = CoreMemory.objects.get_or_create(team=self._team)
        if state.onboarding_question and core_memory.answers_left > 0:
            return "interrupt"
        return "continue"

    def _format_question(self, question: str) -> str:
        if "===" in question:
            question = question.split("===")[1]
        return remove_markdown(question)


class MemoryOnboardingEnquiryInterruptNode(AssistantNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY_INTERRUPT

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        last_assistant_message = find_last_message_of_type(state.messages, AssistantMessage)
        if not state.onboarding_question:
            raise ValueError("No onboarding question found.")
        if last_assistant_message and last_assistant_message.content != state.onboarding_question:
            raise NodeInterrupt(AssistantMessage(content=state.onboarding_question, id=str(uuid4())))
        return PartialAssistantState(onboarding_question=None)


class MemoryOnboardingFinalizeNode(AssistantNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.MEMORY_ONBOARDING_FINALIZE

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        core_memory, _ = CoreMemory.objects.get_or_create(team=self._team)
        # Compress the question/answer memory before saving it
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", ONBOARDING_COMPRESSION_PROMPT),
                ("human", "{memory_content}"),
            ]
        )
        chain = prompt | self._model | StrOutputParser() | compressed_memory_parser
        compressed_memory = cast(str, chain.invoke({"memory_content": core_memory.initial_text}, config=config))
        compressed_memory = compressed_memory.replace("\n", " ").strip()
        core_memory.set_core_memory(compressed_memory)
        return PartialAssistantState(
            messages=[AssistantMessage(content=SCRAPING_MEMORY_SAVED_MESSAGE, id=str(uuid4()))]
        )

    @property
    def _model(self):
        return MaxChatOpenAI(
            model="gpt-4.1-mini",
            temperature=0.3,
            disable_streaming=True,
            stop_sequences=["[Done]"],
            user=self._user,
            team=self._team,
        )


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

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.MEMORY_COLLECTOR

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        if self.should_run_onboarding_at_start(state) != "continue":
            return None

        # Check if the last message is a /remember command
        remember_command_result = self._handle_remember_command(state)
        if remember_command_result:
            return PartialAssistantState(memory_collection_messages=[remember_command_result])

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
            return PartialAssistantState(memory_collection_messages=None)
        return PartialAssistantState(memory_collection_messages=[*node_messages, cast(LangchainAIMessage, response)])

    def router(self, state: AssistantState) -> Literal["tools", "next"]:
        if not state.memory_collection_messages:
            return "next"
        return "tools"

    @property
    def _model(self):
        return MaxChatOpenAI(
            model="gpt-4.1", temperature=0.3, disable_streaming=True, user=self._user, team=self._team
        ).bind_tools(memory_collector_tools)

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

    def _handle_remember_command(self, state: AssistantState) -> LangchainAIMessage | None:
        last_message = state.messages[-1] if state.messages else None
        if (
            not isinstance(last_message, HumanMessage)
            or not last_message.content.split(" ", 1)[0] == SLASH_COMMAND_REMEMBER
        ):
            # Not a /remember command, skip!
            return None

        # Extract the content to remember (everything after "/remember ")
        remember_content = last_message.content[len(SLASH_COMMAND_REMEMBER) :].strip()
        if remember_content:
            # Create a direct memory append tool call
            return LangchainAIMessage(
                content="I'll remember that for you.",
                tool_calls=[
                    {"id": str(uuid4()), "name": "core_memory_append", "args": {"memory_content": remember_content}}
                ],
                id=str(uuid4()),
            )
        else:
            return LangchainAIMessage(content="There's nothing to remember!", id=str(uuid4()))


class MemoryCollectorToolsNode(AssistantNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.MEMORY_COLLECTOR_TOOLS

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        node_messages = state.memory_collection_messages
        if not node_messages:
            raise ValueError("No memory collection messages found.")
        last_message = node_messages[-1]
        if not isinstance(last_message, LangchainAIMessage):
            raise ValueError("Last message must be an AI message.")
        core_memory, _ = CoreMemory.objects.get_or_create(team=self._team)

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
