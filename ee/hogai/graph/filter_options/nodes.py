from functools import cached_property
from typing import cast, Union, Optional

from langchain_core.agents import AgentAction
from langchain_core.messages import (
    merge_message_runs,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from ee.hogai.graph.shared_prompts import PROJECT_ORG_USER_CONTEXT_PROMPT
from ..base import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState

from .prompts import (
    FILTER_INITIAL_PROMPT,
    FILTER_FIELDS_TAXONOMY_PROMPT,
    HUMAN_IN_THE_LOOP_PROMPT,
    USER_FILTER_OPTIONS_PROMPT,
    PRODUCT_DESCRIPTION_PROMPT,
    GROUP_PROPERTY_FILTER_TYPES_PROMPT,
    RESPONSE_FORMATS_PROMPT,
    FILTER_LOGICAL_OPERATORS_PROMPT,
    DATE_FIELDS_PROMPT,
    TOOL_USAGE_PROMPT,
    EXAMPLES_PROMPT,
)
from posthog.models.group_type_mapping import GroupTypeMapping
from pydantic import BaseModel
from .toolkit import final_answer, retrieve_entity_property_values, retrieve_entity_properties, ask_user_for_help
from abc import ABC
import json

from pydantic import ValidationError

from ee.hogai.graph.filter_options.toolkit import FilterOptionsToolkit
from .prompts import (
    REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT,
    FILTER_OPTIONS_ITERATION_LIMIT_PROMPT,
)
from posthog.schema import AssistantToolCallMessage, AssistantMessage
from uuid import uuid4

FilterOptionsToolUnion = Union[
    retrieve_entity_properties,
    retrieve_entity_property_values,
    ask_user_for_help,
    final_answer,
]


class FilterOptionsTool(BaseModel):
    name: str
    arguments: FilterOptionsToolUnion


class FilterOptionsNode(AssistantNode):
    """Node for generating filtering options based on user queries."""

    def __init__(self, team, user, injected_prompts: Optional[dict] = None):
        super().__init__(team, user)
        self.injected_prompts = injected_prompts or {}

    @cached_property
    def _team_group_types(self) -> list[str]:
        return list(
            GroupTypeMapping.objects.filter(project_id=self._team.project.id)
            .order_by("group_type_index")
            .values_list("group_type", flat=True)
        )

    def _get_react_property_filters_prompt(self) -> str:
        return cast(
            str,
            ChatPromptTemplate.from_template(FILTER_FIELDS_TAXONOMY_PROMPT, template_format="mustache")
            .format_messages(groups=self._team_group_types)[0]
            .content,
        )

    def _get_model(self, state: AssistantState):
        return ChatOpenAI(
            model="gpt-4o",
            streaming=False,
            temperature=0.2,
        ).bind_tools(
            [
                retrieve_entity_properties,
                retrieve_entity_property_values,
                ask_user_for_help,
                final_answer,
            ],
            tool_choice="required",
            parallel_tool_calls=False,
        )

    def _construct_messages(self, state: AssistantState) -> ChatPromptTemplate:
        """
        Construct the conversation thread for the agent. Handles both initial conversation setup
        and continuation with intermediate steps.
        """
        # Use injected prompts to build dynamic FILTER_INITIAL_PROMPT
        dynamic_filter_prompt = self._get_filter_generation_prompt(self.injected_prompts)

        # Always include the base system and conversation setup
        system_messages = [
            ("system", PROJECT_ORG_USER_CONTEXT_PROMPT),
            ("system", dynamic_filter_prompt),  # Use dynamic prompt instead of static
            ("system", self._get_react_property_filters_prompt()),
            ("system", HUMAN_IN_THE_LOOP_PROMPT),
        ]

        messages = [*system_messages, ("human", USER_FILTER_OPTIONS_PROMPT)]

        if state.intermediate_steps:
            # Add tool execution context as system messages
            for action, result in state.intermediate_steps:
                if result is not None:
                    tool_context = (
                        f"Tool '{action.tool}' was called with arguments {action.tool_input} and returned: {result}"
                    )
                    messages.append(
                        (
                            "system",
                            f"Tool execution result: {tool_context} \n\nContinue with the next appropriate tool call if needed.",
                        )
                    )

        conversation = ChatPromptTemplate(messages, template_format="mustache")
        return conversation

    def _get_filter_generation_prompt(self, injected_prompts: dict) -> str:
        return cast(
            str,
            ChatPromptTemplate.from_template(FILTER_INITIAL_PROMPT, template_format="mustache")
            .format_messages(
                **{
                    "product_description_prompt": injected_prompts.get(
                        "product_description_prompt", PRODUCT_DESCRIPTION_PROMPT
                    ),
                    "group_property_filter_types_prompt": injected_prompts.get(
                        "group_property_filter_types_prompt", GROUP_PROPERTY_FILTER_TYPES_PROMPT
                    ),
                    "response_formats_prompt": injected_prompts.get("response_formats_prompt", RESPONSE_FORMATS_PROMPT),
                    "filter_logical_operators_prompt": injected_prompts.get(
                        "filter_logical_operators_prompt", FILTER_LOGICAL_OPERATORS_PROMPT
                    ),
                    "date_fields_prompt": injected_prompts.get("date_fields_prompt", DATE_FIELDS_PROMPT),
                    "tool_usage_prompt": injected_prompts.get("tool_usage_prompt", TOOL_USAGE_PROMPT),
                    "examples_prompt": injected_prompts.get("examples_prompt", EXAMPLES_PROMPT),
                }
            )[0]
            .content,
        )

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        """Process the state and return filtering options."""
        conversation = self._construct_messages(state)

        chain = conversation | merge_message_runs() | self._get_model(state)

        change = state.change or ""
        current_filters = str(state.current_filters or {})

        # Handle empty change - provide a helpful default task
        if not change.strip():
            change = "Show me all session recordings with default filters"

        entities = [
            "person",
            "session",
            "event",
            *self._team_group_types,
        ]

        # Use injected prompts if available, otherwise fall back to default prompts
        output_message = chain.invoke(
            {
                "core_memory": self.core_memory.text if self.core_memory else "",
                "groups": entities,
                "project_datetime": self.project_now,
                "project_timezone": self.project_timezone,
                "project_name": self._team.name,
                "organization_name": self._team.organization.name,
                "user_full_name": self._user.get_full_name(),
                "user_email": self._user.email,
                "change": change,
                "current_filters": current_filters,
            },
            config,
        )

        if not output_message.tool_calls:
            raise ValueError("No tool calls found in the output message.")

        tool_call = output_message.tool_calls[0]
        result = AgentAction(tool_call["name"], tool_call["args"], tool_call["id"])

        intermediate_steps = state.intermediate_steps or []
        return PartialAssistantState(
            intermediate_steps=[*intermediate_steps, (result, None)],
            generated_filter_options=state.generated_filter_options,
        )


class FilterOptionsToolsNode(AssistantNode, ABC):
    MAX_ITERATIONS = 5  # Maximum number of iterations for the ReAct agent

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = FilterOptionsToolkit(self._team)
        intermediate_steps = state.intermediate_steps or []
        action, _output = intermediate_steps[-1]
        input = None
        output = ""
        tool_progress_messages: list[AssistantMessage] = []

        try:
            input = FilterOptionsTool.model_validate({"name": action.tool, "arguments": action.tool_input})
        except ValidationError as e:
            output = str(
                ChatPromptTemplate.from_template(REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT, template_format="mustache")
                .format_messages(exception=e.errors(include_url=False))[0]
                .content
            )
        else:
            # First check if we've reached the terminal stage and return the filter options
            if input.name == "final_answer":
                try:
                    # Extract the full response structure
                    full_response = {
                        "result": input.arguments.result,  # type: ignore
                        "data": input.arguments.data,  # type: ignore
                    }

                    return PartialAssistantState(
                        generated_filter_options=full_response,
                        change=state.change,
                        intermediate_steps=[],
                        messages=[
                            AssistantToolCallMessage(
                                tool_call_id=state.root_tool_call_id or "",  # Default to empty string if None
                                content=json.dumps(full_response),
                            )
                        ],
                    )
                except Exception as e:
                    # Fall through to handle as regular tool call
                    output = f"Error processing final answer: {e}"

            # The agent has requested help, so we return a message to the root node
            if input.name == "ask_user_for_help":
                help_message = input.arguments.request  # type: ignore
                return self._get_reset_state(str(help_message), input.name, state)

        # If we're still here, check if we've hit the iteration limit within this cycle
        if len(intermediate_steps) >= self.MAX_ITERATIONS:
            return self._get_reset_state(FILTER_OPTIONS_ITERATION_LIMIT_PROMPT, "max_iterations", state)

        if input and not output:
            # Generate progress message before executing tool

            if input.name == "retrieve_entity_property_values":
                entity = getattr(input.arguments, "entity", "unknown")
                property_name = getattr(input.arguments, "property_name", "unknown")
                tool_progress_messages.append(
                    AssistantMessage(
                        content=f"🔍 Fetching values for {entity} property '{property_name}'...", id=str(uuid4())
                    )
                )
                output = toolkit.retrieve_entity_property_values(input.arguments.entity, input.arguments.property_name)  # type: ignore
            elif input.name == "retrieve_entity_properties":
                entity = getattr(input.arguments, "entity", "unknown")
                tool_progress_messages.append(
                    AssistantMessage(content=f"📋 Loading {entity} properties...", id=str(uuid4()))
                )
                output = toolkit.retrieve_entity_properties(input.arguments.entity)  # type: ignore
            else:
                output = toolkit.handle_incorrect_response(input)

            # Add success message after tool execution
            if input.name in ["retrieve_entity_property_values", "retrieve_entity_properties"] and output:
                if "does not exist" not in output and "not found" not in output:
                    tool_progress_messages.append(AssistantMessage(content=f"✅ Found relevant data", id=str(uuid4())))

        return PartialAssistantState(
            messages=tool_progress_messages,
            intermediate_steps=[*intermediate_steps[:-1], (action, output)],
        )

    def router(self, state: AssistantState):
        # If we have a final answer, end the process
        if state.generated_filter_options:
            return "end"

        # Check if we have help request messages (created by _get_reset_state)
        # These are AssistantToolCallMessage instances with specific help content
        if state.messages:
            last_message = state.messages[-1]
            if isinstance(last_message, AssistantToolCallMessage) and last_message.content:
                if last_message.tool_call_id == "max_iterations" or last_message.tool_call_id == "ask_user_for_help":
                    return "end"

        # Continue normal processing - agent should see tool results and make next decision
        return "continue"

    def _get_reset_state(self, output: str, tool_call_id: str, state: AssistantState):
        reset_state = PartialAssistantState.get_reset_state()
        reset_state.messages = [
            AssistantToolCallMessage(
                tool_call_id=tool_call_id,
                content=output,
            )
        ]
        reset_state.change = state.change
        reset_state.current_filters = state.current_filters
        return reset_state
