import json
import xml.etree.ElementTree as ET
from abc import ABC
from functools import cached_property
from typing import cast

from git import Optional
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    AIMessage as LangchainAssistantMessage,
    BaseMessage,
    ToolMessage as LangchainToolMessage,
    merge_message_runs,
)
from langchain_core.output_parsers import PydanticToolsParser
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from ee.hogai.graph.taxonomy_agent.parsers import parse_langchain_message
from ee.hogai.utils.helpers import remove_line_breaks
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.schema import (
    AssistantToolCall,
    AssistantToolCallMessage,
    CachedTeamTaxonomyQueryResponse,
    TeamTaxonomyQuery,
    VisualizationMessage,
)
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP

from ..base import AssistantNode
from .prompts import (
    CORE_MEMORY_INSTRUCTIONS,
    REACT_ACTIONS_PROMPT,
    REACT_DEFINITIONS_PROMPT,
    REACT_FOLLOW_UP_PROMPT,
    REACT_FORMAT_PROMPT,
    REACT_HELP_REQUEST_PROMPT,
    REACT_HUMAN_IN_THE_LOOP_PROMPT,
    REACT_PROPERTY_FILTERS_PROMPT,
    REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT,
    REACT_REACHED_LIMIT_PROMPT,
    REACT_USER_PROMPT,
)
from .toolkit import TaxonomyAgentToolkit


class TaxonomyAgentPlannerNode(AssistantNode):
    def _run_with_prompt_and_toolkit(
        self,
        state: AssistantState,
        prompt: ChatPromptTemplate,
        toolkit: TaxonomyAgentToolkit,
        config: Optional[RunnableConfig] = None,
    ) -> PartialAssistantState:
        intermediate_steps = state.intermediate_steps or []
        conversation = (
            prompt
            + ChatPromptTemplate.from_messages(
                [
                    ("user", REACT_DEFINITIONS_PROMPT),
                ],
                template_format="mustache",
            )
            + self._construct_messages(state)
        )

        agent = conversation | merge_message_runs() | self._get_model(toolkit)

        result = agent.invoke(
            {
                "react_format": REACT_FORMAT_PROMPT,
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
            },
            config,
        )

        return PartialAssistantState(
            intermediate_steps=[*intermediate_steps, result],
        )

    def _get_model(self, toolkit: TaxonomyAgentToolkit):
        model = ChatAnthropic(
            model="claude-3-7-sonnet-latest",
            temperature=1,
            streaming=True,
            stream_usage=True,
            thinking={"type": "enabled", "budget_tokens": 2000},
            max_tokens=4000,
        )
        return model.bind_tools(toolkit.tools, parallel_tool_calls=False)

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
        # Only process the last ten visualization messages.
        viz_messages = [message for message in state.messages if isinstance(message, VisualizationMessage)][-10:]
        conversation: list[BaseMessage] = []

        for idx, message in enumerate(viz_messages):
            prompt = REACT_USER_PROMPT if idx == 0 else REACT_FOLLOW_UP_PROMPT
            conversation.append(
                HumanMessagePromptTemplate.from_template(prompt, template_format="mustache").format(
                    question=message.query
                )
            )
            conversation.append(LangchainAssistantMessage(content=message.plan or ""))

        # The description of a new insight is added to the end of the conversation.
        new_insight_prompt = REACT_USER_PROMPT if not conversation else REACT_FOLLOW_UP_PROMPT
        conversation.append(
            HumanMessagePromptTemplate.from_template(new_insight_prompt, template_format="mustache").format(
                question=state.root_tool_insight_plan
            )
        )

        if not state.intermediate_steps:
            return conversation

        return [*conversation, *state.intermediate_steps]


class TaxonomyAgentPlannerToolsNode(AssistantNode, ABC):
    MAX_ITERATIONS = 16
    """
    Maximum number of iterations for the ReAct agent. After the limit is reached,
    the agent will terminate the conversation and return a message to the root node
    to request additional information.
    """

    def _run_with_toolkit(
        self, state: AssistantState, toolkit: TaxonomyAgentToolkit, config: Optional[RunnableConfig] = None
    ) -> PartialAssistantState:
        intermediate_steps = state.intermediate_steps or []
        action = intermediate_steps[-1]
        tool_call = parse_langchain_message(action).tool_calls[0]
        assert tool_call is not None

        input = None
        output = ""

        try:
            parser = PydanticToolsParser(tools=toolkit.tools)
            input = parser.invoke(action)
        except ValidationError as e:
            output = str(
                ChatPromptTemplate.from_template(REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT, template_format="mustache")
                .format_messages(exception=e.errors(include_url=False))[0]
                .content
            )
        else:
            # First check if we've reached the terminal stage.
            # The plan has been found. Move to the generation.
            if tool_call.name == "final_answer":
                return PartialAssistantState(
                    plan=tool_call.args["final_response"],
                    intermediate_steps=[],
                )

            # The agent has requested help, so we return a message to the root node.
            if tool_call.name == "ask_user_for_help":
                return self._get_reset_state(state, REACT_HELP_REQUEST_PROMPT.format(request=input.arguments))

        # If we're still here, the final prompt hasn't helped.
        if len(intermediate_steps) >= self.MAX_ITERATIONS:
            return self._get_reset_state(state, REACT_REACHED_LIMIT_PROMPT)

        if input and not output:
            output = self._handle_tool(tool_call, toolkit)

        return PartialAssistantState(
            intermediate_steps=[
                *intermediate_steps,
                LangchainToolMessage(tool_call_id=tool_call.id, content=output),
            ],
        )

    def router(self, state: AssistantState):
        # Human-in-the-loop. Get out of the product analytics subgraph.
        if not state.root_tool_call_id:
            return "end"
        # The plan has been found. Move to the generation.
        if state.plan:
            return "plan_found"
        return "continue"

    def _handle_tool(self, action: AssistantToolCall, toolkit: TaxonomyAgentToolkit) -> str:
        if action.name == "retrieve_event_properties" or action.name == "retrieve_action_properties":
            output = toolkit.retrieve_event_or_action_properties(
                action.args.get("event_name", action.args.get("action_id"))
            )
        elif action.name == "retrieve_event_property_values":
            output = toolkit.retrieve_event_or_action_property_values(
                action.args["event_name"], action.args["property_name"]
            )
        elif action.name == "retrieve_action_property_values":
            output = toolkit.retrieve_event_or_action_property_values(
                action.args["action_id"], action.args["property_name"]
            )
        elif action.name == "retrieve_entity_properties":
            output = toolkit.retrieve_entity_properties(action.args["entity"])
        elif action.name == "retrieve_entity_property_values":
            output = toolkit.retrieve_entity_property_values(action.args["entity"], action.args["property_name"])
        else:
            output = toolkit.handle_incorrect_response(json.dumps(action.args))
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
