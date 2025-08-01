from langchain_core.agents import AgentAction
from langchain_core.messages import (
    merge_message_runs,
    ToolMessage as LangchainToolMessage,
    AIMessage as LangchainAIMessage,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from typing import get_args, get_origin, TypeVar, Generic
from posthog.models import Team, User
from ..base import BaseAssistantNode
from .types import EntityType, TaxonomyAgentState, PartialTaxonomyAgentState
from functools import cached_property
from ee.hogai.llm import MaxChatOpenAI
from posthog.models.group_type_mapping import GroupTypeMapping
from .toolkit import TaxonomyAgentToolkit
from .prompts import (
    PROPERTY_TYPES_PROMPT,
    TAXONOMY_TOOL_USAGE_PROMPT,
    HUMAN_IN_THE_LOOP_PROMPT,
    REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT,
    ITERATION_LIMIT_PROMPT,
)
from ee.hogai.utils.helpers import format_events_prompt

# Type variables with bounds
TaxonomyStateType = TypeVar("TaxonomyStateType", bound=TaxonomyAgentState)
TaxonomyPartialStateType = TypeVar("TaxonomyPartialStateType", bound=PartialTaxonomyAgentState)
TaxonomyNodeBound = BaseAssistantNode[TaxonomyStateType, TaxonomyPartialStateType]


class TaxonomyAgentNode(Generic[TaxonomyStateType, TaxonomyPartialStateType], TaxonomyNodeBound):
    """Base node for taxonomy agents."""

    def __init__(self, team: Team, user: User, toolkit_class: type["TaxonomyAgentToolkit"]):
        super().__init__(team, user)
        self._toolkit = toolkit_class(team=team)
        self._state_class, self._partial_state_class = self._get_state_class()

    def _get_state_class(self) -> tuple[type, type]:
        """Extract the State type from the class's generic parameters."""
        # Check if this class has generic arguments
        if hasattr(self.__class__, "__orig_bases__"):
            for base in self.__class__.__orig_bases__:
                if get_origin(base) is TaxonomyAgentNode:
                    args = get_args(base)
                    if args:
                        return args[0], args[1]  # State is the first argument and PartialState is the second argument

        # No generic type found - use default types
        return TaxonomyAgentState, PartialTaxonomyAgentState

    @cached_property
    def _team_group_types(self) -> list[str]:
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

    def get_system_prompts(self) -> list[str]:
        raise NotImplementedError("get_system_prompts must be implemented in subclasses")

    def _construct_messages(self, state: TaxonomyStateType) -> ChatPromptTemplate:
        """
        Construct the conversation thread for the agent. Handles both initial conversation setup
        and continuation with intermediate steps.
        """
        system_messages = [("system", prompt) for prompt in self.get_system_prompts()]
        system_messages.append(("human", state.instructions))

        progress_messages = list(getattr(state, "tool_progress_messages", []))
        all_messages = [*system_messages, *progress_messages]

        return ChatPromptTemplate(all_messages, template_format="mustache")

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


class TaxonomyAgentToolsNode(Generic[TaxonomyStateType, TaxonomyPartialStateType], TaxonomyNodeBound):
    """Base tools node for taxonomy agents."""

    MAX_ITERATIONS = 10

    def __init__(self, team: Team, user: User, toolkit_class: type["TaxonomyAgentToolkit"]):
        super().__init__(team, user)
        self._toolkit = toolkit_class(team=team)
        self._state_class, self._partial_state_class = self._get_state_class()

    def _get_state_class(self) -> tuple[type, type]:
        """Extract the State type from the class's generic parameters."""
        # Check if this class has generic arguments
        if hasattr(self.__class__, "__orig_bases__"):
            for base in self.__class__.__orig_bases__:
                if get_origin(base) is TaxonomyAgentToolsNode:
                    args = get_args(base)
                    if args:
                        return args[0], args[1]  # State is the first argument and PartialState is the second argument

        # No generic type found - this shouldn't happen in proper usage
        raise ValueError(
            f"Could not determine state type for {self.__class__.__name__}. "
            "Make sure to inherit from TaxonomyAgentToolsNode with a specific state type, "
            "e.g., TaxonomyAgentToolsNode[TaxonomyAgentState, PartialTaxonomyAgentState]"
        )

    def run(self, state: TaxonomyStateType, config: RunnableConfig) -> TaxonomyPartialStateType:
        intermediate_steps = state.intermediate_steps or []
        action, _output = intermediate_steps[-1]
        input = None
        output = ""
        tool_result_msg: list[LangchainToolMessage] = []

        try:
            input = self._toolkit.get_tool_input_model(action)
        except ValidationError as e:
            output = str(
                ChatPromptTemplate.from_template(REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT, template_format="mustache")
                .format_messages(exception=e.errors(include_url=False))[0]
                .content
            )
        else:
            if input.name == "final_answer":  # type: ignore
                return self._partial_state_class(
                    output=input.arguments.data,  # type: ignore
                    intermediate_steps=None,
                )

            # The agent has requested help, so we return a message to the root node
            if input.name == "ask_user_for_help":  # type: ignore
                help_message = input.arguments.request  # type: ignore
                return self._get_reset_state(str(help_message), input.name, state)  # type: ignore

        # If we're still here, check if we've hit the iteration limit within this cycle
        if len(intermediate_steps) >= self.MAX_ITERATIONS:
            return self._get_reset_state(ITERATION_LIMIT_PROMPT, "max_iterations", state)

        if input and not output:
            # Use the toolkit to handle tool execution
            tool_name, output = self._toolkit.handle_tools(input.name, input)  # type: ignore

        if output:
            tool_context = f"Tool '{action.tool}' was called with arguments {action.tool_input} and returned: {output}"
            tool_msg = LangchainToolMessage(
                content=tool_context,
                tool_call_id=action.log,
            )
            tool_result_msg.append(tool_msg)

        old_msg = getattr(state, "tool_progress_messages", [])
        return self._partial_state_class(
            tool_progress_messages=[*old_msg, *tool_result_msg],
            intermediate_steps=[*intermediate_steps[:-1], (action, output)],
        )

    def router(self, state: TaxonomyStateType) -> str:
        # If we have a final answer, end the process
        if state.output:
            return "end"

        # Check if we have help request messages (created by _get_reset_state)
        # These are AssistantToolCallMessage instances with specific help content
        if state.intermediate_steps:
            action, _ = state.intermediate_steps[-1]

            if action.tool == "max_iterations" or action.tool == "ask_user_for_help":
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
        return reset_state  # type: ignore[return-value]
