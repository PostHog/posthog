import json
import xml.etree.ElementTree as ET
from abc import ABC
from functools import cached_property
from typing import cast

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
from pydantic import BaseModel

from ee.hogai.graph.funnels.toolkit import FUNNEL_SCHEMA
from ee.hogai.graph.retention.toolkit import RETENTION_SCHEMA
from ee.hogai.graph.trends.toolkit import TRENDS_SCHEMA

from .prompts import (
    CORE_MEMORY_INSTRUCTIONS,
    QUERY_PLANNER_SYSTEM_PROMPT,
    REACT_ACTIONS_PROMPT,
    REACT_DEFINITIONS_PROMPT,
    REACT_HELP_REQUEST_PROMPT,
    REACT_HUMAN_IN_THE_LOOP_PROMPT,
    REACT_PROPERTY_FILTERS_PROMPT,
    REACT_REACHED_LIMIT_PROMPT,
)
from .toolkit import TaxonomyAgentTool, TaxonomyAgentToolkit, TaxonomyAgentToolUnion
from ee.hogai.utils.helpers import remove_line_breaks
from ..base import AssistantNode
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
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
    event_name: str


class retrieve_action_properties(BaseModel):
    action_id: int


class retrieve_entity_properties(BaseModel):
    entity: str


class retrieve_event_property_values(BaseModel):
    event_name: str
    property_name: str


class retrieve_action_property_values(BaseModel):
    action_id: int
    property_name: str


class retrieve_entity_property_values(BaseModel):
    entity: str
    property_name: str


class ask_user_for_help(BaseModel):
    request: str


LOG_SEPARATOR = ":::"


class QueryPlannerNode(AssistantNode):
    MAX_ITERATIONS = 16
    """
    Maximum number of iterations for the ReAct agent. After the limit is reached,
    the agent will terminate the conversation and return a message to the root node
    to request additional information.
    """

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    [{"type": "text", "text": QUERY_PLANNER_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                ),
                ("user", [{"type": "text", "text": REACT_DEFINITIONS_PROMPT, "cache_control": {"type": "ephemeral"}}]),
            ],
            template_format="mustache",
        )
        conversation = prompt + self._construct_messages(state)

        chain = (
            conversation
            | merge_message_runs()
            | self._model.bind_tools(
                [
                    retrieve_event_properties,
                    retrieve_action_properties,
                    retrieve_entity_properties,
                    retrieve_event_property_values,
                    retrieve_action_property_values,
                    retrieve_entity_property_values,
                    ask_user_for_help,
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

        if output_message.tool_calls:
            tool_call = output_message.tool_calls[0]
            thinking_block = next((block for block in output_message.content if block["type"] == "thinking"), None)
            result = AgentAction(
                tool_call["name"],
                tool_call["args"],
                LOG_SEPARATOR.join([tool_call["id"], thinking_block["thinking"], thinking_block["signature"]])
                if thinking_block
                else tool_call["id"],
            )
            # The agent has requested help, so we return a message to the root node.
            if any(tool_call["name"] == "ask_user_for_help" for tool_call in output_message.tool_calls):
                return self._get_reset_state(
                    state, REACT_HELP_REQUEST_PROMPT.format(request=tool_call["args"]["request"])
                )
            # If we're still here, the final prompt hasn't helped.
            if len(state.intermediate_steps or []) + len(output_message.tool_calls) >= self.MAX_ITERATIONS:
                return self._get_reset_state(state, REACT_REACHED_LIMIT_PROMPT)

            return PartialAssistantState(intermediate_steps=[(result, None)])

        # The plan has been found, move onto generation
        root_tool_insight_type, plan = output_message.text().split("\n", 1)
        root_tool_insight_type = root_tool_insight_type.removeprefix("Insight type: ")
        return PartialAssistantState(plan=plan, root_tool_insight_type=root_tool_insight_type, intermediate_steps=[])

    def router(self, state: AssistantState):
        if state.intermediate_steps:
            return AssistantNodeName.QUERY_PLANNER_TOOLS
        # Human-in-the-loop - get out of the product analytics subgraph
        if not state.root_tool_call_id:
            return "end"
        return state.root_tool_insight_type

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
            conversation.append(
                LangchainHumanMessage(
                    content=f"Plan for this query: {message.query}\nRemember to strictly follow the response format."
                )
            )
            conversation.append(LangchainAssistantMessage(content=message.plan or ""))

        # The description of a new insight is added to the end of the conversation.
        conversation.append(
            LangchainHumanMessage(
                content=f"Plan for this query: {state.root_tool_insight_plan}\nRemember to strictly follow the response format."
            )
        )

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
            conversation.append(LangchainToolMessage(content=output, tool_call_id=tool_call_id))

        return conversation

    def _get_reset_state(self, state: AssistantState, output: str):
        reset_state = PartialAssistantState.get_reset_state()
        reset_state.messages = [
            AssistantToolCallMessage(
                tool_call_id=state.root_tool_call_id,
                content=output,
            )
        ]
        return reset_state


class QueryPlannerToolsNode(AssistantNode, ABC):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = TaxonomyAgentToolkit(self._team)
        intermediate_steps = state.intermediate_steps or []
        action, _output = intermediate_steps[-1]

        input = TaxonomyAgentTool.model_validate(
            {
                "name": action.tool,
                "arguments": next(iter(action.tool_input.values()))
                if action.tool
                in [
                    "retrieve_entity_properties",
                    "retrieve_event_properties",
                    "retrieve_action_properties",
                    "handle_incorrect_response",
                ]
                else action.tool_input,
            }
        ).root

        output = self._handle_tool(input, toolkit) if input else ""

        return PartialAssistantState(
            intermediate_steps=[(action, output)],
        )

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
            output = toolkit.handle_incorrect_response(input.arguments)
        return output
