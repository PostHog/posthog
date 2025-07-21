from abc import ABC
import json

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from ..base import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.graph.filter_options.toolkit import FilterOptionsToolkit
from .nodes import FilterOptionsTool
from .prompts import (
    REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT,
    FILTER_OPTIONS_ITERATION_LIMIT_PROMPT,
)
from posthog.schema import AssistantToolCallMessage, AssistantMessage
from uuid import uuid4


class FilterOptionsToolsNode(AssistantNode, ABC):
    MAX_ITERATIONS = 5  # Maximum number of iterations for the ReAct agent

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = FilterOptionsToolkit(self._team)
        intermediate_steps = state.intermediate_steps or []
        action, _output = intermediate_steps[-1]
        input = None
        output = ""

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
                        filter_options_previous_response_id=state.root_tool_call_id or "",
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
                return self._get_reset_state(str(help_message), input.name)

        # If we're still here, check if we've hit the iteration limit within this cycle
        if len(intermediate_steps) >= self.MAX_ITERATIONS:
            return self._get_reset_state(FILTER_OPTIONS_ITERATION_LIMIT_PROMPT, "max_iterations")

        if input and not output:
            # Generate progress message before executing tool
            progress_messages = []

            if input.name == "retrieve_entity_property_values":
                entity = getattr(input.arguments, "entity", "unknown")
                property_name = getattr(input.arguments, "property_name", "unknown")
                progress_messages.append(
                    AssistantMessage(
                        content=f"🔍 Fetching values for {entity} property '{property_name}'...", id=str(uuid4())
                    )
                )
                output = toolkit.retrieve_entity_property_values(input.arguments.entity, input.arguments.property_name)  # type: ignore
            elif input.name == "retrieve_entity_properties":
                entity = getattr(input.arguments, "entity", "unknown")
                progress_messages.append(
                    AssistantMessage(content=f"📋 Loading {entity} properties...", id=str(uuid4()))
                )
                output = toolkit.retrieve_entity_properties(input.arguments.entity)  # type: ignore
            else:
                output = toolkit.handle_incorrect_response(input)

            # Add success message after tool execution
            if input.name in ["retrieve_entity_property_values", "retrieve_entity_properties"] and output:
                if "does not exist" not in output and "not found" not in output:
                    progress_messages.append(AssistantMessage(content=f"✅ Found relevant data", id=str(uuid4())))

        return PartialAssistantState(
            messages=progress_messages if "progress_messages" in locals() else [],
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

    def _get_reset_state(self, output: str, tool_call_id: str):
        reset_state = PartialAssistantState.get_reset_state()
        reset_state.messages = [
            AssistantToolCallMessage(
                tool_call_id=tool_call_id,
                content=output,
            )
        ]
        return reset_state
