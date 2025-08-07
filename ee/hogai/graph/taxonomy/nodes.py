from abc import ABC, abstractmethod
from langchain_core.agents import AgentAction
from langchain_core.messages import (
    merge_message_runs,
    ToolMessage as LangchainToolMessage,
    AIMessage as LangchainAIMessage,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from typing import Generic, TypeVar
from posthog.models import Team, User

from .types import EntityType, TaxonomyAgentState
from .tools import TaxonomyTool
from functools import cached_property
from ee.hogai.llm import MaxChatOpenAI
from posthog.models.group_type_mapping import GroupTypeMapping
from .toolkit import TaxonomyAgentToolkit
from ..mixins import StateClassMixin
from ..base import BaseAssistantNode
from .prompts import (
    PROPERTY_TYPES_PROMPT,
    TAXONOMY_TOOL_USAGE_PROMPT,
    HUMAN_IN_THE_LOOP_PROMPT,
    REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT,
    ITERATION_LIMIT_PROMPT,
)
from ee.hogai.utils.helpers import format_events_prompt

TaxonomyStateType = TypeVar("TaxonomyStateType", bound=TaxonomyAgentState)
TaxonomyPartialStateType = TypeVar("TaxonomyPartialStateType", bound=TaxonomyAgentState)
TaxonomyNodeBound = BaseAssistantNode[TaxonomyStateType, TaxonomyPartialStateType]


class TaxonomyAgentNode(Generic[TaxonomyStateType, TaxonomyPartialStateType], TaxonomyNodeBound, StateClassMixin, ABC):
    """Base node for taxonomy agents."""

    def __init__(self, team: Team, user: User, toolkit_class: type["TaxonomyAgentToolkit"]):
        super().__init__(team, user)
        self._toolkit = toolkit_class(team=team)
        self._state_class, self._partial_state_class = self._get_state_class(TaxonomyAgentNode)

    @cached_property
    def _team_group_types(self) -> list[str]:
        """Get all available group names for this team."""
        return list(
            GroupTypeMapping.objects.filter(project_id=self._team.project.id)
            .order_by("group_type_index")
            .values_list("group_type", flat=True)
        )

    @cached_property
    def _all_entities(self) -> list[str]:
        """Get all available entities as strings."""
        return EntityType.values() + self._team_group_types

    def _get_model(self, state: TaxonomyStateType):
        return MaxChatOpenAI(
            model="gpt-4.1", streaming=False, temperature=0.3, user=self._user, team=self._team
        ).bind_tools(
            self._toolkit.get_tools(),
            tool_choice="required",
            parallel_tool_calls=False,
        )

    def _get_default_system_prompts(self) -> list[str]:
        """Get the system prompt for this node. Override in subclasses."""
        return [PROPERTY_TYPES_PROMPT, TAXONOMY_TOOL_USAGE_PROMPT, HUMAN_IN_THE_LOOP_PROMPT]

    @abstractmethod
    def _get_system_prompt(self) -> ChatPromptTemplate:
        """Get the system prompt for this node. Must be implemented in subclasses."""

    def _construct_messages(self, state: TaxonomyStateType) -> ChatPromptTemplate:
        """
        Construct the conversation thread for the agent. Handles both initial conversation setup
        and continuation with intermediate steps.
        """
        conversation = self._get_system_prompt().messages
        conversation.append(("human", state.change or ""))

        progress_messages = state.tool_progress_messages or []
        conversation = [*conversation, *progress_messages]

        return ChatPromptTemplate(conversation, template_format="mustache")

    def run(self, state: TaxonomyStateType, config: RunnableConfig) -> TaxonomyPartialStateType:
        """Process the state and return filtering options."""
        progress_messages = state.tool_progress_messages or []
        full_conversation = self._construct_messages(state)

        chain = full_conversation | merge_message_runs() | self._get_model(state)

        events_in_context = []
        if ui_context := self._get_ui_context(state):
            events_in_context = ui_context.events if ui_context.events else []

        output_message = chain.invoke(
            {
                "events": format_events_prompt(events_in_context, self._team),
                "groups": self._team_group_types,
            },
            config,
        )

        if not output_message.tool_calls:
            raise ValueError("No tool calls found in the output message.")

        tool_call = output_message.tool_calls[0]
        result = AgentAction(tool_call["name"], tool_call["args"], tool_call["id"])
        intermediate_steps = state.intermediate_steps or []

        # Add the new AI message to the progress log
        ai_message = LangchainAIMessage(
            content=output_message.content, tool_calls=output_message.tool_calls, id=output_message.id
        )

        return self._partial_state_class(
            tool_progress_messages=[*progress_messages, ai_message],
            intermediate_steps=[*intermediate_steps, (result, None)],
            output=state.output,
        )


class TaxonomyAgentToolsNode(Generic[TaxonomyStateType, TaxonomyPartialStateType], TaxonomyNodeBound, StateClassMixin):
    """Base tools node for taxonomy agents."""

    MAX_ITERATIONS = 10

    def __init__(self, team: Team, user: User, toolkit_class: type["TaxonomyAgentToolkit"]):
        super().__init__(team, user)
        self._toolkit = toolkit_class(team=team)
        self._state_class, self._partial_state_class = self._get_state_class(TaxonomyAgentToolsNode)

    def run(self, state: TaxonomyStateType, config: RunnableConfig) -> TaxonomyPartialStateType:
        intermediate_steps = state.intermediate_steps or []
        action, _output = intermediate_steps[-1]
        tool_input: TaxonomyTool | None = None
        output = ""
        tool_result_msg: list[LangchainToolMessage] = []

        try:
            tool_input = self._toolkit.get_tool_input_model(action)
        except ValidationError as e:
            output = str(
                ChatPromptTemplate.from_template(REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT, template_format="mustache")
                .format_messages(exception=e.errors(include_url=False))[0]
                .content
            )
        else:
            if tool_input.name == "final_answer":
                return self._partial_state_class(
                    output=tool_input.arguments.answer,
                    intermediate_steps=None,
                )

            # The agent has requested help, so we return a message to the root node
            if tool_input.name == "ask_user_for_help":
                return self._get_reset_state(
                    tool_input.arguments.request,
                    tool_input.name,
                    state,
                )

        # If we're still here, check if we've hit the iteration limit within this cycle
        if len(intermediate_steps) >= self.MAX_ITERATIONS:
            return self._get_reset_state(ITERATION_LIMIT_PROMPT, "max_iterations", state)

        if tool_input and not output:
            # Use the toolkit to handle tool execution
            _, output = self._toolkit.handle_tools(tool_input.name, tool_input)

        if output:
            tool_msg = LangchainToolMessage(
                content=output,
                tool_call_id=action.log,
            )
            tool_result_msg.append(tool_msg)

        old_msg = state.tool_progress_messages or []
        return self._partial_state_class(
            tool_progress_messages=[*old_msg, *tool_result_msg],
            intermediate_steps=[*intermediate_steps[:-1], (action, output)],
        )

    def router(self, state: TaxonomyStateType) -> str:
        # If we have a final answer, end the process
        if state.output:
            return "end"

        # Continue normal processing - agent should see tool results and make next decision
        return "continue"

    def _get_reset_state(self, output: str, tool_call_id: str, state: TaxonomyStateType) -> TaxonomyPartialStateType:
        """Reset the state with new intermediate steps while preserving the state type."""
        reset_state = state.__class__.get_reset_state()
        reset_state.intermediate_steps = [
            (
                AgentAction(tool=tool_call_id, tool_input=output, log=""),
                None,
            )
        ]
        reset_state.output = output
        return reset_state  # type: ignore[return-value]
