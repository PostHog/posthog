import json
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
from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, ValidationError, Field, create_model

from ee.hogai.graph.funnels.toolkit import FUNNEL_SCHEMA
from ee.hogai.graph.retention.toolkit import RETENTION_SCHEMA
from ee.hogai.graph.trends.toolkit import TRENDS_SCHEMA
from ee.hogai.tool import MaxSupportedQueryKind

from .prompts import (
    CORE_MEMORY_INSTRUCTIONS,
    QUERY_PLANNER_DYNAMIC_SYSTEM_PROMPT,
    QUERY_PLANNER_STATIC_SYSTEM_PROMPT,
    REACT_ACTIONS_PROMPT,
    REACT_DEFINITIONS_PROMPT,
    REACT_HELP_REQUEST_PROMPT,
    REACT_HUMAN_IN_THE_LOOP_PROMPT,
    REACT_PROPERTY_FILTERS_PROMPT,
    REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT,
    REACT_REACHED_LIMIT_PROMPT,
)
from .toolkit import TaxonomyAgentTool, TaxonomyAgentToolkit, TaxonomyAgentToolUnion
from ee.hogai.utils.helpers import remove_line_breaks
from ..base import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.schema import (
    AssistantToolCallMessage,
    CachedTeamTaxonomyQueryResponse,
    TeamTaxonomyQuery,
    VisualizationMessage,
)
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP


class retrieve_event_properties(BaseModel):
    """
    Use this tool to retrieve the property names of an event. You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

    - **Try other events** if the tool doesn't return any properties.
    - **Prioritize properties that are directly related to the context or objective of the user's query.**
    - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.
    """

    event_name: str = Field(..., description="The name of the event that you want to retrieve properties for.")


class retrieve_action_properties(BaseModel):
    """
    Use this tool to retrieve the property names of an action. You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

    - **Try other actions or events** if the tool doesn't return any properties.
    - **Prioritize properties that are directly related to the context or objective of the user's query.**
    - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.
    """

    action_id: int = Field(..., description="The ID of the action that you want to retrieve properties for.")


class retrieve_entity_properties(BaseModel):
    """
    Use this tool to retrieve property names for a property group (entity). You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

    - **Infer the property groups from the user's request.**
    - **Try other entities** if the tool doesn't return any properties.
    - **Prioritize properties that are directly related to the context or objective of the user's query.**
    - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.
    """

    entity: Literal["person", "session"] = Field(
        ..., description="The type of the entity that you want to retrieve properties for."
    )


class retrieve_event_property_values(BaseModel):
    """
    Use this tool to retrieve the property values for an event. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.
    """

    event_name: str = Field(..., description="The name of the event that you want to retrieve values for.")
    property_name: str = Field(..., description="The name of the property that you want to retrieve values for.")


class retrieve_action_property_values(BaseModel):
    """
    Use this tool to retrieve the property values for an action. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.
    """

    action_id: int = Field(..., description="The ID of the action that you want to retrieve values for.")
    property_name: str = Field(..., description="The name of the property that you want to retrieve values for.")


class retrieve_entity_property_values(BaseModel):
    """
    Use this tool to retrieve property values for a property name. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.
    """

    entity: Literal["person", "session"] = Field(
        ..., description="The type of the entity that you want to retrieve properties for."
    )
    property_name: str = Field(..., description="The name of the property that you want to retrieve values for.")


class ask_user_for_help(BaseModel):
    """
    Use this tool to ask a question to the user. Your question must be concise and clear.
    """

    request: str = Field(..., description="The question you want to ask.")


class final_answer(BaseModel):
    query_kind: MaxSupportedQueryKind = Field(
        ..., description="What kind of query to create. Only use SQL as an escape hatch, or if the user asks for it."
    )
    plan: str = Field(..., description="Query plan strictly following the response format.")


LOG_SEPARATOR = ":::"


class QueryPlannerNode(AssistantNode):
    def _get_dynamic_entity_tools(self):
        """Create dynamic Pydantic models with correct entity types for this team."""
        # Get the actual entity names for this team (same logic as toolkit)
        entities = ["person", "session", *self._team_group_types]

        # Create Literal type with actual entity names
        entity_literal = Literal[tuple(entities)]

        # Create dynamic retrieve_entity_properties model
        DynamicRetrieveEntityProperties = create_model(
            "retrieve_entity_properties",
            entity=(
                entity_literal,
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
        DynamicRetrieveEntityPropertyValues = create_model(
            "retrieve_entity_property_values",
            entity=(
                entity_literal,
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

        return DynamicRetrieveEntityProperties, DynamicRetrieveEntityPropertyValues

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    [
                        {
                            "type": "text",
                            "text": QUERY_PLANNER_STATIC_SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {"type": "text", "text": QUERY_PLANNER_DYNAMIC_SYSTEM_PROMPT},
                    ],
                ),
                ("user", REACT_DEFINITIONS_PROMPT),
            ],
            template_format="mustache",
        )
        conversation = prompt + self._construct_messages(state)

        # Get dynamic entity tools with correct types for this team
        DynamicRetrieveEntityProperties, DynamicRetrieveEntityPropertyValues = self._get_dynamic_entity_tools()

        chain = (
            conversation
            | merge_message_runs()
            | self._model.bind_tools(
                [
                    retrieve_event_properties,
                    retrieve_action_properties,
                    DynamicRetrieveEntityProperties,
                    retrieve_event_property_values,
                    retrieve_action_property_values,
                    DynamicRetrieveEntityPropertyValues,
                    ask_user_for_help,
                    final_answer,
                ],
            )
        )

        output_message = chain.invoke(
            {
                "core_memory": self.core_memory.text if self.core_memory else "",
                "react_property_filters": self._get_react_property_filters_prompt(),
                "react_human_in_the_loop": REACT_HUMAN_IN_THE_LOOP_PROMPT,
                "groups": self._team_group_types,
                "events": self._events_prompt,
                "core_memory_instructions": CORE_MEMORY_INSTRUCTIONS,
                "project_datetime": self.project_now,
                "project_timezone": self.project_timezone,
                "project_name": self._team.name,
                "actions": state.rag_context,
                "actions_prompt": REACT_ACTIONS_PROMPT,
                "trends_json_schema": TRENDS_SCHEMA,
                "funnel_json_schema": FUNNEL_SCHEMA,
                "retention_json_schema": RETENTION_SCHEMA,
            },
            config,
        )

        if not output_message.tool_calls:
            raise ValueError("No tool calls found in the output message.")

        tool_call = output_message.tool_calls[0]
        thinking_block = next((block for block in output_message.content if block["type"] == "thinking"), None)
        result = AgentAction(
            tool_call["name"],
            tool_call["args"],
            LOG_SEPARATOR.join([tool_call["id"], thinking_block["thinking"], thinking_block["signature"]])
            if thinking_block
            else tool_call["id"],
        )

        return PartialAssistantState(intermediate_steps=[(result, None)])

    @property
    def _model(self) -> ChatAnthropic:
        return ChatAnthropic(
            model="claude-sonnet-4-20250514",
            thinking={"type": "enabled", "budget_tokens": 12000},
            max_tokens=4000,
            model_kwargs={"extra_headers": {"anthropic-beta": "interleaved-thinking-2025-05-14"}},
            streaming=True,
            stream_usage=True,
        )

    def _get_react_property_filters_prompt(self) -> str:
        return cast(
            str,
            ChatPromptTemplate.from_template(REACT_PROPERTY_FILTERS_PROMPT, template_format="mustache")
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
            conversation.append(LangchainHumanMessage(content=message.query))
            conversation.append(LangchainAssistantMessage(content=message.plan or ""))

        # The description of a new insight is added to the end of the conversation.
        conversation.append(LangchainHumanMessage(content=state.root_tool_insight_plan))

        for action, output in state.intermediate_steps or []:
            tool_call_id = action.log.split(LOG_SEPARATOR)[0]
            conversation.append(
                LangchainAssistantMessage(
                    content=[
                        {
                            "type": "tool_use",
                            "id": tool_call_id,
                            "name": action.tool,
                            "partial_json": json.dumps(action.tool_input),
                        },
                    ],
                    tool_calls=[{"id": tool_call_id, "name": action.tool, "args": action.tool_input}],
                )
            )
            if action.log and LOG_SEPARATOR in action.log:
                _tool_call_id, thinking_content, thinking_signature = action.log.split(LOG_SEPARATOR)
                conversation[-1].content.insert(
                    0,
                    {
                        "type": "thinking",
                        "thinking": thinking_content,
                        "signature": thinking_signature,
                    },
                )
            conversation.append(LangchainToolMessage(content=output or "", tool_call_id=tool_call_id))

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
            input = TaxonomyAgentTool.model_validate(
                {
                    "name": action.tool,
                    "arguments": next(iter(action.tool_input.values()))
                    if action.tool
                    in [
                        "retrieve_entity_properties",
                        "retrieve_event_properties",
                        "retrieve_action_properties" "ask_user_for_help",
                    ]
                    else action.tool_input,
                }
            ).root
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
                    intermediate_steps=[],
                )

            # The agent has requested help, so we return a message to the root node.
            if input.name == "ask_user_for_help":
                return self._get_reset_state(state, REACT_HELP_REQUEST_PROMPT.format(request=input.arguments))

        # If we're still here, the final prompt hasn't helped.
        if len(intermediate_steps) >= self.MAX_ITERATIONS:
            return self._get_reset_state(state, REACT_REACHED_LIMIT_PROMPT)

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
        if input.name == "retrieve_event_properties" or input.name == "retrieve_action_properties":
            output = toolkit.retrieve_event_or_action_properties(input.arguments)
        elif input.name == "retrieve_event_property_values":
            output = toolkit.retrieve_event_or_action_property_values(
                input.arguments.event_name, input.arguments.property_name
            )
        elif input.name == "retrieve_action_property_values":
            output = toolkit.retrieve_event_or_action_property_values(
                input.arguments.action_id, input.arguments.property_name
            )
        elif input.name == "retrieve_entity_properties":
            output = toolkit.retrieve_entity_properties(input.arguments)
        elif input.name == "retrieve_entity_property_values":
            output = toolkit.retrieve_entity_property_values(input.arguments.entity, input.arguments.property_name)
        else:
            output = toolkit.handle_incorrect_response(
                input.arguments if isinstance(input.arguments, str) else json.dumps(input.arguments)
            )
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
