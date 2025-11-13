from abc import ABC, abstractmethod
from collections import defaultdict
from functools import cached_property
from typing import Generic, TypeVar

from langchain_core.agents import AgentAction
from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    ToolMessage as LangchainToolMessage,
    merge_message_runs,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from posthog.schema import MaxEventContext

from posthog.models import Team, User
from posthog.models.group_type_mapping import GroupTypeMapping

from ee.hogai.graph.taxonomy.tools import TaxonomyTool
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.utils.helpers import format_events_yaml

from ..base import BaseAssistantNode
from ..mixins import StateClassMixin, TaxonomyUpdateDispatcherNodeMixin
from .prompts import (
    HUMAN_IN_THE_LOOP_PROMPT,
    ITERATION_LIMIT_PROMPT,
    PROPERTY_TYPES_PROMPT,
    REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT,
    TAXONOMY_TOOL_USAGE_PROMPT,
)
from .toolkit import TaxonomyAgentToolkit
from .types import EntityType, TaxonomyAgentState

TaxonomyStateType = TypeVar("TaxonomyStateType", bound=TaxonomyAgentState)
TaxonomyPartialStateType = TypeVar("TaxonomyPartialStateType", bound=TaxonomyAgentState)
TaxonomyNodeBound = BaseAssistantNode[TaxonomyStateType, TaxonomyPartialStateType]


class TaxonomyAgentNode(
    Generic[TaxonomyStateType, TaxonomyPartialStateType],
    StateClassMixin,
    TaxonomyUpdateDispatcherNodeMixin,
    TaxonomyNodeBound,
    ABC,
):
    """Base node for taxonomy agents."""

    def __init__(self, team: Team, user: User, toolkit_class: type["TaxonomyAgentToolkit"]):
        super().__init__(team, user)
        self._toolkit = toolkit_class(team=team, user=user)
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
        # Check if this invocation should be billable (set by the calling tool)
        billable = getattr(state, "billable", False)
        return MaxChatOpenAI(
            model="gpt-4.1",
            streaming=False,
            temperature=0.3,
            user=self._user,
            team=self._team,
            disable_streaming=True,
            billable=billable,
        ).bind_tools(
            self._toolkit.get_tools(),
            tool_choice="required",
            parallel_tool_calls=True,
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
        conversation = list(self._get_system_prompt().messages)
        human_content = state.change or ""
        all_messages = [*conversation, ("human", human_content)]

        progress_messages = state.tool_progress_messages or []
        all_messages.extend(progress_messages)

        return ChatPromptTemplate(all_messages, template_format="mustache")

    def _format_events(self, events_in_context: list[MaxEventContext]) -> str:
        """
        Generate the output format for events. Can be overridden by subclasses.
        Default implementation uses YAML format but it can be overridden to use XML format.
        """
        return format_events_yaml(events_in_context, self._team)

    def run(self, state: TaxonomyStateType, config: RunnableConfig) -> TaxonomyPartialStateType:
        """Process the state and return filtering options."""
        self.dispatch_update_message(state)
        progress_messages = state.tool_progress_messages or []
        full_conversation = self._construct_messages(state)

        chain = full_conversation | merge_message_runs() | self._get_model(state)

        events_in_context = []
        if ui_context := self.context_manager.get_ui_context(state):
            events_in_context = ui_context.events if ui_context.events else []

        output_message = chain.invoke(
            {
                "events": self._format_events(events_in_context),
                "groups": self._team_group_types,
            },
            config,
        )

        if not output_message.tool_calls:
            raise ValueError("No tool calls found in the output message.")

        tool_calls = output_message.tool_calls
        # Preserve previous intermediate steps (and their results)
        previous_steps = state.intermediate_steps or []
        intermediate_steps = [*previous_steps]
        for tool_call in tool_calls:
            result = AgentAction(tool_call["name"], tool_call["args"], tool_call["id"])
            intermediate_steps.append((result, None))

        # Add the new AI message to the progress log
        ai_message = LangchainAIMessage(
            content=output_message.content, tool_calls=output_message.tool_calls, id=output_message.id
        )

        return self._partial_state_class(
            tool_progress_messages=[*progress_messages, ai_message],
            intermediate_steps=intermediate_steps,
            output=state.output,
            iteration_count=state.iteration_count + 1 if state.iteration_count is not None else 1,
            billable=state.billable,
        )


class TaxonomyAgentToolsNode(
    Generic[TaxonomyStateType, TaxonomyPartialStateType],
    StateClassMixin,
    TaxonomyUpdateDispatcherNodeMixin,
    TaxonomyNodeBound,
):
    """Base tools node for taxonomy agents."""

    MAX_ITERATIONS = 10

    def __init__(self, team: Team, user: User, toolkit_class: type["TaxonomyAgentToolkit"]):
        super().__init__(team, user)
        self._toolkit = toolkit_class(team=team, user=user)
        self._state_class, self._partial_state_class = self._get_state_class(TaxonomyAgentToolsNode)

    async def arun(self, state: TaxonomyStateType, config: RunnableConfig) -> TaxonomyPartialStateType:
        intermediate_steps = state.intermediate_steps or []
        tools_metadata: dict[str, list[tuple[TaxonomyTool, str]]] = defaultdict(list)
        invalid_tools = []
        steps = []
        tool_msgs = []
        for action, observation in intermediate_steps:
            if observation is not None:
                steps.append((action, observation))
                continue
            try:
                tool_input = self._toolkit.get_tool_input_model(action)
            except ValidationError as e:
                output = str(
                    ChatPromptTemplate.from_template(
                        REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT, template_format="mustache"
                    )
                    .format_messages(exception=e.errors(include_url=False))[0]
                    .content
                )
                steps.append((action, output))
                tool_msgs.append(
                    LangchainToolMessage(
                        content=output,
                        tool_call_id=action.log,
                    )
                )
                invalid_tools.append(action.log)
                continue
            else:
                if tool_input.name == "final_answer":
                    return self._partial_state_class(
                        output=tool_input.arguments.answer,  # type: ignore
                        intermediate_steps=None,
                        billable=state.billable,
                    )

                if tool_input.name == "ask_user_for_help":
                    return self._get_reset_state(
                        tool_input.arguments.request,  # type: ignore
                        tool_input.name,
                        state,
                    )

                # For any other tool, collect metadata and prepare for result processing
                tools_metadata[tool_input.name].append((tool_input, action.log))

        # If we're still here, check if we've hit the iteration limit within this cycle
        if state.iteration_count is not None and state.iteration_count >= self.MAX_ITERATIONS:
            return self._get_reset_state(ITERATION_LIMIT_PROMPT, "max_iterations", state)

        self.dispatch_update_message(state)

        tool_results = await self._toolkit.handle_tools(tools_metadata)

        for action, observation in intermediate_steps:
            if observation is not None:
                continue
            if action.log in invalid_tools:
                continue
            tool_result = tool_results[action.log]
            tool_msg = LangchainToolMessage(
                content=tool_result,
                tool_call_id=action.log,
            )
            tool_msgs.append(tool_msg)
            steps.append((action, tool_result))

        old_msg = state.tool_progress_messages or []

        return self._partial_state_class(
            tool_progress_messages=[*old_msg, *tool_msgs],
            intermediate_steps=steps,
            iteration_count=state.iteration_count,
            billable=state.billable,
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
        reset_state.billable = state.billable
        return reset_state  # type: ignore[return-value]
