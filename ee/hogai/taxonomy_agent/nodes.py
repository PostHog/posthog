import itertools
import xml.etree.ElementTree as ET
from abc import ABC
from functools import cached_property
from typing import cast

from git import Optional
from langchain.agents.format_scratchpad import format_log_to_str
from langchain_core.agents import AgentAction
from langchain_core.messages import AIMessage as LangchainAssistantMessage, BaseMessage, merge_message_runs
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from ee.hogai.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
from ee.hogai.taxonomy_agent.parsers import (
    ReActParserException,
    ReActParserMissingActionException,
    parse_react_agent_output,
)
from ee.hogai.taxonomy_agent.prompts import (
    REACT_DEFINITIONS_PROMPT,
    REACT_FOLLOW_UP_PROMPT,
    REACT_FORMAT_PROMPT,
    REACT_FORMAT_REMINDER_PROMPT,
    REACT_MALFORMED_JSON_PROMPT,
    REACT_MISSING_ACTION_CORRECTION_PROMPT,
    REACT_MISSING_ACTION_PROMPT,
    REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT,
    REACT_SCRATCHPAD_PROMPT,
    REACT_USER_PROMPT,
)
from ee.hogai.taxonomy_agent.toolkit import TaxonomyAgentTool, TaxonomyAgentToolkit
from ee.hogai.utils import AssistantNode, AssistantState, filter_visualization_conversation, remove_line_breaks
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.schema import (
    CachedTeamTaxonomyQueryResponse,
    TeamTaxonomyQuery,
)


class TaxonomyAgentPlannerNode(AssistantNode):
    def _run_with_prompt_and_toolkit(
        self,
        state: AssistantState,
        prompt: ChatPromptTemplate,
        toolkit: TaxonomyAgentToolkit,
        config: Optional[RunnableConfig] = None,
    ) -> AssistantState:
        intermediate_steps = state.get("intermediate_steps") or []
        conversation = (
            prompt
            + ChatPromptTemplate.from_messages(
                [
                    ("user", REACT_DEFINITIONS_PROMPT),
                ],
                template_format="mustache",
            )
            + self._construct_messages(state)
            + ChatPromptTemplate.from_messages(
                [
                    ("user", REACT_SCRATCHPAD_PROMPT),
                ],
                template_format="mustache",
            )
        )

        agent = conversation | merge_message_runs() | self._model | parse_react_agent_output

        try:
            result = cast(
                AgentAction,
                agent.invoke(
                    {
                        "react_format": REACT_FORMAT_PROMPT,
                        "react_format_reminder": REACT_FORMAT_REMINDER_PROMPT,
                        "tools": toolkit.render_text_description(),
                        "tool_names": ", ".join([t["name"] for t in toolkit.tools]),
                        "product_description": self._team.project.product_description,
                        "groups": self._team_group_types,
                        "events": self._events_prompt,
                        "agent_scratchpad": self._get_agent_scratchpad(intermediate_steps),
                    },
                    config,
                ),
            )
        except ReActParserException as e:
            if isinstance(e, ReActParserMissingActionException):
                # When the agent doesn't output the "Action:" block, we need to correct the log and append the action block,
                # so that it has a higher chance to recover.
                corrected_log = str(
                    ChatPromptTemplate.from_template(REACT_MISSING_ACTION_CORRECTION_PROMPT, template_format="mustache")
                    .format_messages(output=e.llm_output)[0]
                    .content
                )
                result = AgentAction(
                    "handle_incorrect_response",
                    REACT_MISSING_ACTION_PROMPT,
                    corrected_log,
                )
            else:
                result = AgentAction(
                    "handle_incorrect_response",
                    REACT_MALFORMED_JSON_PROMPT,
                    e.llm_output,
                )

        return {
            "intermediate_steps": [*intermediate_steps, (result, None)],
        }

    def router(self, state: AssistantState):
        if state.get("intermediate_steps", []):
            return "tools"
        raise ValueError("Invalid state.")

    @property
    def _model(self) -> ChatOpenAI:
        return ChatOpenAI(model="gpt-4o", temperature=0.2, streaming=True)

    @cached_property
    def _events_prompt(self) -> str:
        response = TeamTaxonomyQueryRunner(TeamTaxonomyQuery(), self._team).run(
            ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
        )

        if not isinstance(response, CachedTeamTaxonomyQueryResponse):
            raise ValueError("Failed to generate events prompt.")

        events: list[str] = [
            # Add "All Events" to the mapping
            "All Events",
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
                    if label := event_core_definition.get("label"):
                        desc_tag.text = f"{label}. {description}"
                    else:
                        desc_tag.text = description
                    desc_tag.text = remove_line_breaks(desc_tag.text)
        return ET.tostring(root, encoding="unicode")

    @cached_property
    def _team_group_types(self) -> list[str]:
        return list(
            GroupTypeMapping.objects.filter(team=self._team)
            .order_by("group_type_index")
            .values_list("group_type", flat=True)
        )

    def _construct_messages(self, state: AssistantState) -> list[BaseMessage]:
        """
        Reconstruct the conversation for the agent. On this step we only care about previously asked questions and generated plans. All other messages are filtered out.
        """
        human_messages, visualization_messages = filter_visualization_conversation(state.get("messages", []))

        if not human_messages:
            return []

        conversation = []

        for idx, messages in enumerate(itertools.zip_longest(human_messages, visualization_messages)):
            human_message, viz_message = messages

            if human_message:
                if idx == 0:
                    conversation.append(
                        HumanMessagePromptTemplate.from_template(REACT_USER_PROMPT, template_format="mustache").format(
                            question=human_message.content
                        )
                    )
                else:
                    conversation.append(
                        HumanMessagePromptTemplate.from_template(
                            REACT_FOLLOW_UP_PROMPT,
                            template_format="mustache",
                        ).format(feedback=human_message.content)
                    )

            if viz_message:
                conversation.append(LangchainAssistantMessage(content=viz_message.plan or ""))

        return conversation

    def _get_agent_scratchpad(self, scratchpad: list[tuple[AgentAction, str | None]]) -> str:
        actions = []
        for action, observation in scratchpad:
            if observation is None:
                continue
            actions.append((action, observation))
        return format_log_to_str(actions)


class TaxonomyAgentPlannerToolsNode(AssistantNode, ABC):
    def _run_with_toolkit(
        self, state: AssistantState, toolkit: TaxonomyAgentToolkit, config: Optional[RunnableConfig] = None
    ) -> AssistantState:
        intermediate_steps = state.get("intermediate_steps") or []
        action, _ = intermediate_steps[-1]

        try:
            input = TaxonomyAgentTool.model_validate({"name": action.tool, "arguments": action.tool_input}).root
        except ValidationError as e:
            observation = (
                ChatPromptTemplate.from_template(REACT_PYDANTIC_VALIDATION_EXCEPTION_PROMPT, template_format="mustache")
                .format_messages(exception=e.errors(include_url=False))[0]
                .content
            )
            return {"intermediate_steps": [*intermediate_steps[:-1], (action, str(observation))]}

        # The plan has been found. Move to the generation.
        if input.name == "final_answer":
            return {
                "plan": input.arguments,
                "intermediate_steps": None,
            }

        output = ""
        if input.name == "retrieve_event_properties":
            output = toolkit.retrieve_event_properties(input.arguments)
        elif input.name == "retrieve_event_property_values":
            output = toolkit.retrieve_event_property_values(input.arguments.event_name, input.arguments.property_name)
        elif input.name == "retrieve_entity_properties":
            output = toolkit.retrieve_entity_properties(input.arguments)
        elif input.name == "retrieve_entity_property_values":
            output = toolkit.retrieve_entity_property_values(input.arguments.entity, input.arguments.property_name)
        else:
            output = toolkit.handle_incorrect_response(input.arguments)

        return {"intermediate_steps": [*intermediate_steps[:-1], (action, output)]}

    def router(self, state: AssistantState):
        if state.get("plan") is not None:
            return "plan_found"
        return "continue"
