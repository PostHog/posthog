from langchain_core.agents import AgentAction
from langchain_core.messages import (
    merge_message_runs,
    ToolMessage as LangchainToolMessage,
    AIMessage as LangchainAIMessage,
)

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from ee.hogai.graph.taxonomy import TaxonomyAgentNode, TaxonomyAgentToolsNode
from .types import TaxonomyAgentState, PartialTaxonomyAgentState
from .prompts import (
    USER_FILTER_OPTIONS_PROMPT,
    REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT,
    FILTER_OPTIONS_ITERATION_LIMIT_PROMPT,
    FILTER_FIELDS_TAXONOMY_PROMPT,
    DATE_FIELDS_PROMPT,
)
from .toolkit import TaxonomyAgentToolkit

from pydantic import ValidationError
from ee.hogai.utils.helpers import format_events_prompt


class FilterOptionsNode(TaxonomyAgentNode):
    """Node for generating filtering options based on user queries."""

    def __init__(self, team, user, toolkit_class: type[TaxonomyAgentToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)

    def _get_default_system_prompts(self) -> list[str]:
        """Get default system prompts. Override in subclasses for custom prompts."""

        return [FILTER_FIELDS_TAXONOMY_PROMPT, DATE_FIELDS_PROMPT, *super()._get_default_system_prompts()]

    def _construct_messages(self, state: TaxonomyAgentState) -> ChatPromptTemplate:
        """
        Construct the conversation thread for the agent. Handles both initial conversation setup
        and continuation with intermediate steps.
        """
        system_messages = [("system", prompt) for prompt in self._get_default_system_prompts()]
        system_messages.append(("human", USER_FILTER_OPTIONS_PROMPT))

        progress_messages = list(getattr(state, "tool_progress_messages", []))
        all_messages = [*system_messages, *progress_messages]

        return ChatPromptTemplate(all_messages, template_format="mustache")

    def run(self, state: TaxonomyAgentState, config: RunnableConfig) -> PartialTaxonomyAgentState:
        """Process the state and return filtering options."""
        progress_messages = state.tool_progress_messages or []
        full_conversation = self._construct_messages(state)

        chain = full_conversation | merge_message_runs() | self._get_model(state)

        change = state.change or ""
        current_filters = str(state.current_filters or {})

        # Handle empty change - provide a helpful default task
        if not change.strip():
            change = "Show me all session recordings with default filters"

        events_in_context = []
        if ui_context := self._get_ui_context(state):
            events_in_context = ui_context.events if ui_context.events else []

        # Use injected prompts if available, otherwise fall back to default prompts
        output_message = chain.invoke(
            {
                "change": change,
                "current_filters": current_filters,
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
        return PartialTaxonomyAgentState(
            tool_progress_messages=[*progress_messages, ai_message],
            intermediate_steps=[*intermediate_steps, (result, None)],
            output=state.output,
        )


class FilterOptionsToolsNode(TaxonomyAgentToolsNode):
    MAX_ITERATIONS = 10

    def __init__(self, team, user, toolkit_class: type[TaxonomyAgentToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)

    def run(self, state: TaxonomyAgentState, config: RunnableConfig) -> PartialTaxonomyAgentState:
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
            # First check if we've reached the terminal stage and return the filter options
            if input.name == "final_answer":
                full_response = {
                    "data": input.arguments.data,  # type: ignore
                }

                return PartialTaxonomyAgentState(
                    output=full_response,
                    intermediate_steps=None,
                )

            # The agent has requested help, so we return a message to the root node
            if input.name == "ask_user_for_help":
                help_message = input.arguments.request  # type: ignore
                return self._get_reset_state(str(help_message), input.name, state)

        # If we're still here, check if we've hit the iteration limit within this cycle
        if len(intermediate_steps) >= self.MAX_ITERATIONS:
            return self._get_reset_state(FILTER_OPTIONS_ITERATION_LIMIT_PROMPT, "max_iterations", state)

        if input and not output:
            # Use the toolkit to handle tool execution
            tool_name, output = self._toolkit.handle_tools(input.name, input)

        if output:
            tool_context = f"Tool '{action.tool}' was called with arguments {action.tool_input} and returned: {output}"
            tool_msg = LangchainToolMessage(
                content=tool_context,
                tool_call_id=action.log,
            )
            tool_result_msg.append(tool_msg)

        old_msg = getattr(state, "tool_progress_messages", [])
        return PartialTaxonomyAgentState(
            tool_progress_messages=[*old_msg, *tool_result_msg],
            intermediate_steps=[*intermediate_steps[:-1], (action, output)],
        )

    def router(self, state: TaxonomyAgentState):
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
