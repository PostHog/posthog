from functools import cached_property

from langchain_core.agents import AgentAction
from langchain_core.messages import (
    merge_message_runs,
    ToolMessage as LangchainToolMessage,
    AIMessage as LangchainAIMessage,
)

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from ee.hogai.graph.base import FilterOptionsBaseNode
from .types import FilterOptionsState, PartialFilterOptionsState
from ee.hogai.graph.query_planner.toolkit import (
    retrieve_entity_properties,
    retrieve_entity_property_values,
    retrieve_event_properties,
    retrieve_event_property_values,
)

from .prompts import (
    USER_FILTER_OPTIONS_PROMPT,
    GROUPS_PROMPT,
    REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT,
    FILTER_OPTIONS_ITERATION_LIMIT_PROMPT,
)
from posthog.models.group_type_mapping import GroupTypeMapping
from .toolkit import EntityType, FilterOptionsTool, FilterOptionsToolkit, ask_user_for_help, create_final_answer_model

from abc import ABC
from ee.hogai.tool import get_filter_profile
from pydantic import ValidationError
from ee.hogai.llm import MaxChatOpenAI


class FilterOptionsNode(FilterOptionsBaseNode):
    """Node for generating filtering options based on user queries."""

    def __init__(self, team, user):
        super().__init__(team, user)

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

    def _get_filter_profile(self, state: FilterOptionsState):
        """Get the filter profile for this tool. Raises error if not found."""
        if not state.tool_name:
            raise ValueError("tool_name is required in state for filter generation")

        profile = get_filter_profile(state.tool_name)
        if not profile:
            raise ValueError(
                f"No FilterProfile registered for tool '{state.tool_name}'. Register a FilterProfile before using filter generation."
            )
        return profile

    def _get_model(self, state: FilterOptionsState):
        # Create dynamic final_answer tool based on filter profile
        filter_profile = self._get_filter_profile(state)
        dynamic_final_answer = create_final_answer_model(filter_profile.response_model)

        return MaxChatOpenAI(
            model="gpt-4.1", streaming=False, temperature=0.3, user=self._user, team=self._team
        ).bind_tools(
            [
                retrieve_entity_properties,
                retrieve_entity_property_values,
                retrieve_event_properties,
                retrieve_event_property_values,
                ask_user_for_help,
                dynamic_final_answer,
            ],
            tool_choice="required",
            parallel_tool_calls=False,
        )

    def _construct_messages(self, state: FilterOptionsState) -> ChatPromptTemplate:
        """
        Construct the conversation thread for the agent. Handles both initial conversation setup
        and continuation with intermediate steps.
        """
        system_messages = [("system", self._get_filter_generation_prompt(state)), ("human", USER_FILTER_OPTIONS_PROMPT)]
        messages = [*system_messages]

        progress_messages = list(getattr(state, "tool_progress_messages", []))
        all_messages = [*messages, *progress_messages]

        full_conversation = ChatPromptTemplate(all_messages, template_format="mustache")

        return full_conversation

    def _get_filter_generation_prompt(self, state: FilterOptionsState) -> str:
        filter_profile = self._get_filter_profile(state)

        if not filter_profile.formatted_prompt:
            raise ValueError(
                f"FilterProfile for tool '{state.tool_name}' has no formatted_prompt set. The tool must format the prompt before using the graph."
            )

        groups_prompt = (
            ChatPromptTemplate.from_template(GROUPS_PROMPT, template_format="mustache")
            .format_messages(groups=self._team_group_types)[0]
            .content
        )

        return f"{filter_profile.formatted_prompt}\n\n{groups_prompt}"

    def run(self, state: FilterOptionsState, config: RunnableConfig) -> PartialFilterOptionsState:
        """Process the state and return filtering options."""
        progress_messages = state.tool_progress_messages or []
        full_conversation = self._construct_messages(state)

        chain = full_conversation | merge_message_runs() | self._get_model(state)

        change = state.change or ""
        current_filters = str(state.current_filters or {})

        # Handle empty change - provide a helpful default task
        if not change.strip():
            change = "Show me all session recordings with default filters"

        # Use filter profile if available, otherwise fall back to default prompts
        output_message = chain.invoke(
            {
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

        # Add the new AI message to the progress log
        ai_message = LangchainAIMessage(
            content=output_message.content, tool_calls=output_message.tool_calls, id=output_message.id
        )
        return PartialFilterOptionsState(
            tool_progress_messages=[*progress_messages, ai_message],
            intermediate_steps=[*intermediate_steps, (result, None)],
            generated_filter_options=state.generated_filter_options,
            tool_name=state.tool_name,
        )


class FilterOptionsToolsNode(FilterOptionsBaseNode, ABC):
    MAX_ITERATIONS = 10  # Maximum number of iterations for the ReAct agent

    def run(self, state: FilterOptionsState, config: RunnableConfig) -> PartialFilterOptionsState:
        toolkit = FilterOptionsToolkit(self._team)
        intermediate_steps = state.intermediate_steps or []
        action, _output = intermediate_steps[-1]
        input = None
        output = ""
        tool_result_msg: list[LangchainToolMessage] = []

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
                # Extract the full response structure
                full_response = {
                    "data": input.arguments.data,  # type: ignore
                }

                return PartialFilterOptionsState(
                    generated_filter_options=full_response,
                    intermediate_steps=None,
                    tool_name=state.tool_name,
                )

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
                output = toolkit.retrieve_entity_property_values(input.arguments.entity, input.arguments.property_name)  # type: ignore
            elif input.name == "retrieve_entity_properties":
                output = toolkit.retrieve_entity_properties(input.arguments.entity)  # type: ignore
            elif input.name == "retrieve_event_property_values":
                output = toolkit.retrieve_event_or_action_property_values(
                    input.arguments.event_name,  # type: ignore
                    input.arguments.property_name,  # type: ignore
                )
            elif input.name == "retrieve_event_properties":
                output = toolkit.retrieve_event_or_action_properties(input.arguments.event_name)  # type: ignore
            else:
                output = toolkit.handle_incorrect_response(input)

        if output:
            tool_context = f"Tool '{action.tool}' was called with arguments {action.tool_input} and returned: {output}"
            tool_msg = LangchainToolMessage(
                content=tool_context,
                tool_call_id=action.log,
            )
            tool_result_msg.append(tool_msg)

        old_msg = getattr(state, "tool_progress_messages", [])
        return PartialFilterOptionsState(
            tool_progress_messages=[*old_msg, *tool_result_msg],
            intermediate_steps=[*intermediate_steps[:-1], (action, output)],
            tool_name=state.tool_name,
        )

    def router(self, state: FilterOptionsState):
        # If we have a final answer, end the process
        if state.generated_filter_options:
            return "end"

        # Check if we have help request messages (created by _get_reset_state)
        # These are AssistantToolCallMessage instances with specific help content
        if state.intermediate_steps:
            action, _ = state.intermediate_steps[-1]

            if action.tool == "max_iterations" or action.tool == "ask_user_for_help":
                return "end"

        # Continue normal processing - agent should see tool results and make next decision
        return "continue"

    def _get_reset_state(self, output: str, tool_call_id: str, state: FilterOptionsState) -> PartialFilterOptionsState:
        reset_state = PartialFilterOptionsState.get_reset_state()
        reset_state.intermediate_steps = [
            (
                AgentAction(tool=tool_call_id, tool_input=output, log=""),
                None,
            )
        ]
        reset_state.tool_name = state.tool_name
        return reset_state
