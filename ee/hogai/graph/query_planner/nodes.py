import xml.etree.ElementTree as ET
from abc import ABC
from functools import cached_property
from typing import cast, Literal

from langchain_core.agents import AgentAction
from langchain_core.messages import (
    AIMessage as LangchainAssistantMessage,
    BaseMessage,
    ToolMessage as LangchainToolMessage,
    HumanMessage as LangchainHumanMessage,
    merge_message_runs,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import ValidationError, Field, create_model

from ee.hogai.graph.root.prompts import ROOT_INSIGHT_DESCRIPTION_PROMPT

from .prompts import (
    CORE_MEMORY_INSTRUCTIONS,
    QUERY_PLANNER_DYNAMIC_SYSTEM_PROMPT,
    QUERY_PLANNER_STATIC_SYSTEM_PROMPT,
    ACTIONS_EXPLANATION_PROMPT,
    EVENT_DEFINITIONS_PROMPT,
    REACT_HELP_REQUEST_PROMPT,
    HUMAN_IN_THE_LOOP_PROMPT,
    PROPERTY_FILTERS_EXPLANATION_PROMPT,
    REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT,
    ITERATION_LIMIT_PROMPT,
)
from .toolkit import (
    TaxonomyAgentTool,
    TaxonomyAgentToolkit,
    TaxonomyAgentToolUnion,
    retrieve_event_properties,
    retrieve_action_properties,
    retrieve_event_property_values,
    retrieve_action_property_values,
    ask_user_for_help,
    final_answer,
)
from ee.hogai.utils.helpers import remove_line_breaks
from ..base import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantRetentionQuery,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    CachedTeamTaxonomyQueryResponse,
    TeamTaxonomyQuery,
    VisualizationMessage,
)
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP


class QueryPlannerNode(AssistantNode):
    def _get_dynamic_entity_tools(self):
        """Create dynamic Pydantic models with correct entity types for this team."""
        # Create Literal type with actual entity names
        DynamicEntityLiteral = Literal["person", "session", *self._team_group_types]  # type: ignore
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

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        if not state.query_planner_previous_response_id:
            conversation = ChatPromptTemplate(
                [
                    (
                        "system",
                        [
                            {
                                "type": "text",
                                "text": QUERY_PLANNER_STATIC_SYSTEM_PROMPT,
                            },
                            {
                                "type": "text",
                                "text": EVENT_DEFINITIONS_PROMPT,
                            },
                            {"type": "text", "text": QUERY_PLANNER_DYNAMIC_SYSTEM_PROMPT},
                        ],
                    ),
                ],
                template_format="mustache",
            ) + self._construct_messages(state)
        else:
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

        chain = conversation | merge_message_runs() | self._get_model(state)

        output_message = chain.invoke(
            {
                "core_memory": self.core_memory.text if self.core_memory else "",
                "react_property_filters": self._get_react_property_filters_prompt(),
                "react_human_in_the_loop": HUMAN_IN_THE_LOOP_PROMPT,
                "groups": self._team_group_types,
                "events": self._events_prompt,
                "core_memory_instructions": CORE_MEMORY_INSTRUCTIONS,
                "project_datetime": self.project_now,
                "project_timezone": self.project_timezone,
                "project_name": self._team.name,
                "actions": state.rag_context,
                "actions_prompt": ACTIONS_EXPLANATION_PROMPT,
                "trends_json_schema": AssistantTrendsQuery.model_json_schema(),
                "funnel_json_schema": AssistantFunnelsQuery.model_json_schema(),
                "retention_json_schema": AssistantRetentionQuery.model_json_schema(),
                "insight_types_prompt": ROOT_INSIGHT_DESCRIPTION_PROMPT,
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
            query_planner_previous_response_id=output_message.response_metadata["id"],
        )

    def _get_model(self, state: AssistantState):
        # Get dynamic entity tools with correct types for this team
        dynamic_retrieve_entity_properties, dynamic_retrieve_entity_property_values = self._get_dynamic_entity_tools()

        return ChatOpenAI(
            model="o3",
            use_responses_api=True,
            streaming=False,
            model_kwargs={
                "reasoning": {"summary": "auto"},
                "previous_response_id": state.query_planner_previous_response_id or None,  # Must alias "" to None
            },
        ).bind_tools(
            [
                retrieve_event_properties,
                retrieve_action_properties,
                dynamic_retrieve_entity_properties,
                retrieve_event_property_values,
                retrieve_action_property_values,
                dynamic_retrieve_entity_property_values,
                ask_user_for_help,
                final_answer,
            ],
            tool_choice="required",
            parallel_tool_calls=False,
        )

    def _get_react_property_filters_prompt(self) -> str:
        return cast(
            str,
            ChatPromptTemplate.from_template(PROPERTY_FILTERS_EXPLANATION_PROMPT, template_format="mustache")
            .format_messages(groups=self._team_group_types)[0]
            .content,
        )

    @cached_property
    def _events_prompt(self) -> str:
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
            if len(response.results) > 25 and item.count <= 3:
                continue
            events.append(item.event)

        root = ET.Element("defined_events")
        for event_name in events:
            event_tag = ET.SubElement(root, "event")
            name_tag = ET.SubElement(event_tag, "name")
            name_tag.text = event_name

            if event_core_definition := CORE_FILTER_DEFINITIONS_BY_GROUP["events"].get(event_name):
                if event_core_definition.get("system") or event_core_definition.get("ignored_in_assistant"):
                    continue  # Skip irrelevant events
                if description := event_core_definition.get("description"):
                    desc_tag = ET.SubElement(event_tag, "description")
                    if label := event_core_definition.get("label_llm") or event_core_definition.get("label"):
                        desc_tag.text = f"{label}. {description}"
                    else:
                        desc_tag.text = description
                    desc_tag.text = remove_line_breaks(desc_tag.text)
        return ET.tostring(root, encoding="unicode")

    @cached_property
    def _team_group_types(self) -> list[str]:
        return list(
            GroupTypeMapping.objects.filter(project_id=self._team.project_id)
            .order_by("group_type_index")
            .values_list("group_type", flat=True)
        )

    def _construct_messages(self, state: AssistantState) -> list[BaseMessage]:
        """
        Reconstruct the conversation for the agent. On this step we only care about previously asked questions and generated plans. All other messages are filtered out.
        """
        conversation: list[BaseMessage] = []

        # Only process the last ten visualization messages.
        viz_messages = [message for message in state.messages if isinstance(message, VisualizationMessage)][-10:]
        for message in viz_messages:
            conversation.append(LangchainHumanMessage(content=message.query or "_No query description provided._"))
            conversation.append(LangchainAssistantMessage(content=message.plan or "_No generated plan._"))

        # The description of a new insight is added to the end of the conversation.
        conversation.append(
            LangchainHumanMessage(content=state.root_tool_insight_plan or "_No query description provided._")
        )

        return conversation


class QueryPlannerToolsNode(AssistantNode, ABC):
    MAX_ITERATIONS = 16
    """
    Maximum number of iterations for the ReAct agent. After the limit is reached,
    the agent will terminate the conversation and return a message to the root node
    to request additional information.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = TaxonomyAgentToolkit(self._team)
        intermediate_steps = state.intermediate_steps or []
        action, _output = intermediate_steps[-1]

        input = None
        output = ""

        try:
            input = TaxonomyAgentTool.model_validate({"name": action.tool, "arguments": action.tool_input})
        except ValidationError as e:
            output = str(
                ChatPromptTemplate.from_template(REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT, template_format="mustache")
                .format_messages(exception=e.errors(include_url=False))[0]
                .content
            )
        else:
            # First check if we've reached the terminal stage.
            # The plan has been found. Move to the generation.
            if input.name == "final_answer":
                return PartialAssistantState(
                    plan=input.arguments.plan,
                    root_tool_insight_type=input.arguments.query_kind,
                    query_planner_previous_response_id="",
                    intermediate_steps=[],
                )

            # The agent has requested help, so we return a message to the root node.
            if input.name == "ask_user_for_help":
                return self._get_reset_state(state, REACT_HELP_REQUEST_PROMPT.format(request=input.arguments))

        # If we're still here, the final prompt hasn't helped.
        if len(intermediate_steps) >= self.MAX_ITERATIONS:
            return self._get_reset_state(state, ITERATION_LIMIT_PROMPT)

        if input and not output:
            output = self._handle_tool(input, toolkit)

        return PartialAssistantState(
            intermediate_steps=[*intermediate_steps[:-1], (action, output)],
        )

    def router(self, state: AssistantState):
        # Human-in-the-loop. Get out of the product analytics subgraph.
        if not state.root_tool_call_id:
            return "end"
        # The plan has been found. Move to the generation.
        if state.plan:
            return state.root_tool_insight_type
        return "continue"

    def _handle_tool(self, input: TaxonomyAgentToolUnion, toolkit: TaxonomyAgentToolkit) -> str:
        if input.name == "retrieve_event_properties":
            output = toolkit.retrieve_event_or_action_properties(input.arguments.event_name)
        elif input.name == "retrieve_action_properties":
            output = toolkit.retrieve_event_or_action_properties(input.arguments.action_id)
        elif input.name == "retrieve_event_property_values":
            output = toolkit.retrieve_event_or_action_property_values(
                input.arguments.event_name, input.arguments.property_name
            )
        elif input.name == "retrieve_action_property_values":
            output = toolkit.retrieve_event_or_action_property_values(
                input.arguments.action_id, input.arguments.property_name
            )
        elif input.name == "retrieve_entity_properties":
            output = toolkit.retrieve_entity_properties(input.arguments.entity)
        elif input.name == "retrieve_entity_property_values":
            output = toolkit.retrieve_entity_property_values(input.arguments.entity, input.arguments.property_name)
        else:
            output = toolkit.handle_incorrect_response(input)
        return output

    def _get_reset_state(self, state: AssistantState, output: str):
        reset_state = PartialAssistantState.get_reset_state()
        reset_state.messages = [
            AssistantToolCallMessage(
                tool_call_id=state.root_tool_call_id,
                content=output,
            )
        ]
        return reset_state
