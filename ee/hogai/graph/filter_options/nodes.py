from functools import cached_property
from typing import cast, Union

from langchain_core.agents import AgentAction
from langchain_core.messages import (
    merge_message_runs,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from ee.hogai.graph.shared_prompts import CORE_MEMORY_PROMPT, PROJECT_ORG_USER_CONTEXT_PROMPT
from ..base import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState

from .prompts import (
    FILTER_INITIAL_PROMPT,
    FILTER_PROPERTIES_PROMPT,
    FILTER_SET_PROMPT,
    HUMAN_IN_THE_LOOP_PROMPT,
    USER_FILTER_OPTIONS_PROMPT,
)
from posthog.models.group_type_mapping import GroupTypeMapping
from pydantic import BaseModel
from .toolkit import final_answer, retrieve_entity_property_values, retrieve_entity_properties, ask_user_for_help

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

    @cached_property
    def _team_group_types(self) -> list[str]:
        return list(
            GroupTypeMapping.objects.filter(project_id=self._team.project.id)
            .order_by("group_type_index")
            .values_list("group_type", flat=True)
        )

    @cached_property
    def _team_groups(self) -> list[GroupTypeMapping]:
        return list(GroupTypeMapping.objects.filter(project_id=self._team.project.id).order_by("group_type_index"))

    def _get_react_property_filters_prompt(self) -> str:
        return cast(
            str,
            ChatPromptTemplate.from_template(FILTER_PROPERTIES_PROMPT, template_format="mustache")
            .format_messages(groups=self._team_group_types)[0]
            .content,
        )

    def _get_current_set_filters_prompt(self, current_set_filters: str) -> str:
        return cast(
            str,
            ChatPromptTemplate.from_template(FILTER_SET_PROMPT, template_format="mustache")
            .format_messages(current_set_filters=current_set_filters)[0]
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
        # Always include the base system and conversation setup
        system_messages = [
            ("system", FILTER_INITIAL_PROMPT),
            ("system", CORE_MEMORY_PROMPT),
            ("system", PROJECT_ORG_USER_CONTEXT_PROMPT),
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
                            f"Tool execution result: {tool_context} \n\nContinue with the next appropriate tool call.",
                        )
                    )

        conversation = ChatPromptTemplate(messages, template_format="mustache")
        return conversation

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

        output_message = chain.invoke(
            {
                "core_memory": self.core_memory.text if self.core_memory else "",
                "groups": entities,
                "react_property_filters": self._get_react_property_filters_prompt(),
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
