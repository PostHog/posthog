from abc import ABC
from typing import cast, Literal

from langchain_core.agents import AgentAction
from langchain_core.messages import ToolMessage as LangchainToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from ..base import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.models.team.team import Team
from posthog.models.user import User
from ee.hogai.graph.query_planner.toolkit import TaxonomyAgentTool, TaxonomyAgentToolkit
from .nodes import FilterOptionsTool
from .prompts import (
    FILTER_OPTIONS_HELP_REQUEST_PROMPT,
    REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT,
    FILTER_OPTIONS_ITERATION_LIMIT_PROMPT,
)
from posthog.schema import AssistantToolCallMessage

class FilterOptionsToolsNode(AssistantNode, ABC):
    MAX_ITERATIONS = 3  # Maximum number of iterations for the ReAct agent

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = TaxonomyAgentToolkit(self._team)
        intermediate_steps = state.intermediate_steps or []
        action, _output = intermediate_steps[-1]

        input = None
        output = ""

        try:
            # print(f"DEBUG: action: {action}")
            # print(f"DEBUG: action.tool_input: {action.tool_input}")
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
                import json

                try:
                    # Extract the full response structure
                    full_response = {
                        "result": input.arguments.result,  # type: ignore
                        "data": input.arguments.data  # type: ignore
                    }
                    # print(f"DEBUG: final_answer full_response: {full_response}")
                    return PartialAssistantState(
                        filter_options_dict=full_response,
                        filter_options_previous_response_id="",
                        intermediate_steps=[],
                        # Preserve the original change and current_filters from the state
                        change=state.change,
                        current_filters=state.current_filters,
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
                print(f"DEBUG: ask_user_for_help called with request: '{input.arguments.request}'")  # type: ignore
                help_message = input.arguments.request  # type: ignore
                return self._get_reset_state(state, str(help_message))

        # If we're still here, check if we've hit the iteration limit
        if len(intermediate_steps) >= self.MAX_ITERATIONS:
            return self._get_reset_state(state, FILTER_OPTIONS_ITERATION_LIMIT_PROMPT)

        if input and not output:
            # Use the toolkit to handle the tool call
            if input.name == "dynamic_retrieve_entity_properties":
                output = toolkit.retrieve_entity_properties(input.arguments.entity)  # type: ignore
            elif input.name == "dynamic_retrieve_entity_property_values":
                output = toolkit.retrieve_entity_property_values(input.arguments.entity, input.arguments.property_name)  # type: ignore
            elif input.name == "retrieve_entity_properties":
                output = toolkit.retrieve_entity_properties(input.arguments.entity)  # type: ignore
            elif input.name == "retrieve_entity_property_values":
                output = toolkit.retrieve_entity_property_values(input.arguments.entity, input.arguments.property_name)  # type: ignore
            else:
                output = toolkit.handle_incorrect_response(input)

        return PartialAssistantState(
            intermediate_steps=[*intermediate_steps[:-1], (action, output)],
            # Preserve the original change and current_filters from the state
            change=state.change,
            current_filters=state.current_filters,
        )

    def router(self, state: AssistantState):
        # If we have a plan, end the process
        if state.filter_options_dict:
            # print("DEBUG: Router returning 'end' - has filter_options_dict")
            return "end"
        # Human-in-the-loop. Get out of the filter options subgraph.
        # Only treat empty string as help request, not other falsy values
        if state.root_tool_call_id == "":
            # print("DEBUG: Router returning 'end' - empty root_tool_call_id (help request)")
            return "end"
        # If we need more information, continue the process
        # print("DEBUG: Router returning 'continue'")
        return "continue"

    def _get_reset_state(self, state: AssistantState, output: str):
        reset_state = PartialAssistantState.get_reset_state()
        reset_state.messages = [
            AssistantToolCallMessage(
                tool_call_id=state.root_tool_call_id or "",  # Default to empty string if None
                content=output,
            )
        ]
        # Preserve the original change and current_filters from the state
        # reset_state.change = state.change
        reset_state.current_filters = state.current_filters
        return reset_state 
