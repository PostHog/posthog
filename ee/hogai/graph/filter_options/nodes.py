import xml.etree.ElementTree as ET
from abc import ABC
from functools import cached_property
from typing import cast, Literal, Optional, Union

from langchain_core.agents import AgentAction
from langchain_core.messages import (
    ToolMessage as LangchainToolMessage,
    merge_message_runs,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import ValidationError, Field, create_model

from ee.hogai.graph.shared_prompts import CORE_MEMORY_PROMPT, PROJECT_ORG_USER_CONTEXT_PROMPT
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database, serialize_database
from ..base import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.models.team.team import Team
from posthog.models.user import User

from .prompts import FILTER_INITIAL_PROMPT, FILTER_PROPERTIES_PROMPT, FILTER_SET_PROMPT, HUMAN_IN_THE_LOOP_PROMPT, USER_FILTER_OPTIONS_PROMPT
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.schema import (
    AssistantToolCallMessage,
    CachedTeamTaxonomyQueryResponse,
    MaxEventContext,
    TeamTaxonomyQuery,
)
from ee.hogai.graph.query_planner.toolkit import (
    TaxonomyAgentTool,
    TaxonomyAgentToolkit,
    retrieve_event_properties,
    retrieve_action_properties,
    retrieve_event_property_values,
    retrieve_action_property_values,
    ask_user_for_help,
    retrieve_entity_property_values,
)
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
from ee.hogai.utils.helpers import remove_line_breaks
from pydantic import BaseModel

class final_answer(BaseModel):
    """
    Use this tool to finalize the filter options answer.
    """
    
    result: str = Field(description="Should be 'filter' for filter responses")
    data: dict = Field(description="Complete filter object as defined in the prompts")

# Import the other tools we need
from ee.hogai.graph.query_planner.toolkit import (
    retrieve_event_properties,
    retrieve_action_properties,
    retrieve_event_property_values,
    retrieve_action_property_values,
    ask_user_for_help,
    retrieve_entity_property_values,
    retrieve_entity_properties,
)

FilterOptionsToolUnion = Union[
    ask_user_for_help,
    retrieve_entity_property_values,
    retrieve_entity_properties,
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

    def _get_dynamic_entity_tools(self):
        """Create dynamic Pydantic models with correct entity types for this team."""
        # Create Literal type with actual entity names
        DynamicEntityLiteral = Literal["person", "session", "actions", *self._team_group_types]  # type: ignore
        # Create dynamic retrieve_entity_properties model
        retrieve_entity_properties_dynamic = create_model(
            "retrieve_entity_properties",
            entity=(
                DynamicEntityLiteral,
                Field(..., description="The type of the entity that you want to retrieve properties for."),
            ),
            __doc__="""
            Use this tool to retrieve property names for a property group (entity). You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

            - **Infer the property groups from the user's request.**
            - **Try other entities** if the tool doesn't return any properties.
            - **Prioritize properties that are directly related to the context or objective of the user's query.**
            - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.
            """,
        )
        # Create dynamic retrieve_entity_property_values model
        retrieve_entity_property_values_dynamic = create_model(
            "retrieve_entity_property_values",
            entity=(
                DynamicEntityLiteral,
                Field(..., description="The type of the entity that you want to retrieve properties for."),
            ),
            property_name=(
                str,
                Field(..., description="The name of the property that you want to retrieve values for."),
            ),
            __doc__="""
            Use this tool to retrieve property values for a property name. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.
            """,
        )

        return retrieve_entity_properties_dynamic, retrieve_entity_property_values_dynamic

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
        # Get dynamic entity tools with correct types for this team
        dynamic_retrieve_entity_properties, dynamic_retrieve_entity_property_values = self._get_dynamic_entity_tools()

        return ChatOpenAI(
            model="o4-mini",
            streaming=False,
            model_kwargs={
                "reasoning": {"summary": "auto"},
                "previous_response_id": state.filter_options_previous_response_id or None,  # Must alias "" to None
            },
            
        ).bind_tools(
            [
                # dynamic_retrieve_entity_properties,
                # dynamic_retrieve_entity_property_values,
                # Put final_answer last so it's less likely to be chosen early
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
        if not state.filter_options_previous_response_id:
            
            # Create separate templates for system and conversation
            system_messages = [
                ("system", FILTER_INITIAL_PROMPT),
                ("system", CORE_MEMORY_PROMPT),
                ("system", PROJECT_ORG_USER_CONTEXT_PROMPT),
                ("system", HUMAN_IN_THE_LOOP_PROMPT),
            ]

            # Add the conversation prompt with variables
            conversation = ChatPromptTemplate(
                system_messages + [("human", USER_FILTER_OPTIONS_PROMPT)],
                template_format="mustache"
            )
        else:
            # Continuation with intermediate steps
            if not state.intermediate_steps:
                raise ValueError("No intermediate steps found in the state.")
            conversation = ChatPromptTemplate(
                [
                    LangchainToolMessage(
                        content=state.intermediate_steps[-1][1] or "",
                        tool_call_id=state.intermediate_steps[-1][0].log or "",
                    )
                ]
            )

        return conversation

    def _format_events_prompt(self, events_in_context: list[MaxEventContext]) -> str:
        response = TeamTaxonomyQueryRunner(TeamTaxonomyQuery(), self._team).run(
            ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
        )

        if not isinstance(response, CachedTeamTaxonomyQueryResponse):
            raise ValueError("Failed to generate events prompt.")

        events: list[str] = [
            # Add "All events" to the mapping
            "All events",
        ]
        for item in response.results:
            # Skip events that have less than 3 occurrences, we assume that they are not relevant to the user's query
            if len(response.results) > 25 and item.count <= 3:
                continue
            events.append(item.event)
        event_to_description: dict[str, str] = {}
        for event in events_in_context:
            if event.name and event.name not in events:
                events.append(event.name)
                if event.description:
                    event_to_description[event.name] = event.description

        # Create a set of event names from context for efficient lookup
        context_event_names = {event.name for event in events_in_context if event.name}

        root = ET.Element("defined_events")
        for event_name in events:
            event_tag = ET.SubElement(root, "event")
            name_tag = ET.SubElement(event_tag, "name")
            name_tag.text = event_name

            if event_core_definition := CORE_FILTER_DEFINITIONS_BY_GROUP["events"].get(event_name):
                if event_name not in context_event_names and (
                    event_core_definition.get("system") or event_core_definition.get("ignored_in_assistant")
                ):
                    continue  # Skip irrelevant events but keep events the user has added to the context
                if description := event_core_definition.get("description"):
                    desc_tag = ET.SubElement(event_tag, "description")
                    if label := event_core_definition.get("label_llm") or event_core_definition.get("label"):
                        desc_tag.text = f"{label}. {description}"
                    else:
                        desc_tag.text = description
                    desc_tag.text = remove_line_breaks(desc_tag.text)
            elif event_name in event_to_description:
                desc_tag = ET.SubElement(event_tag, "description")
                desc_tag.text = event_to_description[event_name]
                desc_tag.text = remove_line_breaks(desc_tag.text)
        return ET.tostring(root, encoding="unicode")

    def _handle_tool(self, input: TaxonomyAgentTool, toolkit: TaxonomyAgentToolkit) -> str:
        if input.name == "retrieve_entity_properties":
            output = toolkit.retrieve_entity_properties(input.arguments.entity)  # type: ignore
        elif input.name == "retrieve_entity_property_values":
            output = toolkit.retrieve_entity_property_values(input.arguments.entity, input.arguments.property_name)  # type: ignore
        else:
            output = toolkit.handle_incorrect_response(input)
        return output

    def _get_reset_state(self, state: AssistantState, output: str):

        reset_state = PartialAssistantState.get_reset_state()
        if state.root_tool_call_id:
            reset_state.messages = [
                AssistantToolCallMessage(
                    tool_call_id=state.root_tool_call_id,
                    content=output,
                )
            ]
        return reset_state
    
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        """Process the state and return filtering options."""
        conversation = self._construct_messages(state)

        chain = conversation | merge_message_runs() | self._get_model(state)

        print("DEBUG: groups")
        print(self._team_group_types)
        # events_in_context = []
            
        # if ui_context := self._get_ui_context(state):
        #     events_in_context = ui_context.events if ui_context.events else []

        print("DEBUG: state")
        print(state)
        # Get change and current_filters from the initial state
        # These are passed when invoking the graph

        change = state.change or ""
        current_filters_dict = state.current_filters or {}
        current_filters = str(current_filters_dict)

        # Handle empty change - provide a helpful default task
        if not change.strip():
            change = "Show me all session recordings with default filters"
    
        output_message = chain.invoke(
            {
                "core_memory": self.core_memory.text if self.core_memory else "",
                # Not sure if events need to be in the prompt itself, my idea is to use the tool to retrieve them
                # "events": self._format_events_prompt(events_in_context),

                # Explain how to use the property filters
                "groups": self._team_group_types,
                "react_property_filters": self._get_react_property_filters_prompt(),
                # "current_set_filters": self._get_current_set_filters_prompt(current_filters),
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
            print("DEBUG: No tool calls found - this should end the conversation")
            return PartialAssistantState(
                intermediate_steps=[],
                filter_options_previous_response_id=output_message.response_metadata["id"],
                filter_options_dict=state.filter_options_dict,
            )
        else:
            tool_call = output_message.tool_calls[0]
            result = AgentAction(tool_call["name"], tool_call["args"], tool_call["id"])

            intermediate_steps = state.intermediate_steps or []

            return PartialAssistantState(
                intermediate_steps=[*intermediate_steps, (result, None)],
                filter_options_previous_response_id=output_message.response_metadata["id"],
            )
