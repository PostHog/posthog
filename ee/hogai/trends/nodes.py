import xml.etree.ElementTree as ET
from typing import Literal, Union, cast

from langchain.agents.format_scratchpad import format_log_to_str
from langchain.agents.output_parsers import ReActJsonSingleInputOutputParser
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import merge_message_runs
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from pydantic import ValidationError

from ee.hogai.hardcoded_definitions import hardcoded_prop_defs
from ee.hogai.trends.prompts import react_definitions_prompt, react_scratchpad_prompt, react_system_prompt
from ee.hogai.trends.toolkit import TrendsAgentToolkit, TrendsAgentToolModel
from ee.hogai.utils import (
    AssistantNode,
    AssistantNodeName,
    AssistantState,
    llm_gpt_4o,
    remove_line_breaks,
)
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.team.team import Team
from posthog.schema import CachedTeamTaxonomyQueryResponse, TeamTaxonomyQuery


class CreateTrendsPlanNode(AssistantNode):
    name = AssistantNodeName.CREATE_TRENDS_PLAN

    @classmethod
    def _generate_events_prompt(cls, team: Team) -> str:
        event_description_mapping = {
            "$identify": "Identifies an anonymous user. This event doesn't show how many users you have but rather how many users used an account."
        }

        response = TeamTaxonomyQueryRunner(TeamTaxonomyQuery(), team).run(
            ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
        )

        if not isinstance(response, CachedTeamTaxonomyQueryResponse):
            raise ValueError("Failed to generate events prompt.")

        events = [item.event for item in response.results]

        # default for null in the schema
        tags: list[str] = ["all events"]

        for event_name in events:
            event_tag = event_name
            if event_name in event_description_mapping:
                description = event_description_mapping[event_name]
                event_tag += f" - {description}"
            elif event_name in hardcoded_prop_defs["events"]:
                data = hardcoded_prop_defs["events"][event_name]
                event_tag += f" - {data['label']}. {data['description']}"
                if "examples" in data:
                    event_tag += f" Examples: {data['examples']}."
            tags.append(remove_line_breaks(event_tag))

        root = ET.Element("list of available events for filtering")
        root.text = "\n" + "\n".join(tags) + "\n"
        return ET.tostring(root, encoding="unicode")

    @classmethod
    def _retrieve_group_types(cls, team: Team) -> list[str]:
        return list(
            GroupTypeMapping.objects.filter(team=team).order_by("group_type_index").values_list("group_type", flat=True)
        )

    @classmethod
    def router(
        cls,
        state: AssistantState,
    ) -> Literal[AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS, AssistantNodeName.GENERATE_TRENDS]:
        # Invalid state
        if (
            state["agent_state"] is None
            or "intermediate_steps" not in state["agent_state"]
            or len(state["agent_state"]["intermediate_steps"]) == 0
        ):
            raise ValueError("Invalid state.")

        # The plan was generated.
        action, _ = state["agent_state"]["intermediate_steps"][-1]
        if action.tool == "final_answer":
            return AssistantNodeName.GENERATE_TRENDS

        return AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS

    @classmethod
    def run(cls, state: AssistantState) -> AssistantState:
        team = state["team"]
        messages = state["messages"]
        agent_state = state.get("agent_state")
        intermediate_steps = agent_state["intermediate_steps"] if agent_state is not None else []

        prompt = (
            ChatPromptTemplate.from_messages(
                [
                    ("system", react_system_prompt),
                    ("user", react_definitions_prompt),
                ],
                template_format="mustache",
            )
            + messages
            + ChatPromptTemplate.from_messages(
                [
                    ("user", react_scratchpad_prompt),
                ],
                template_format="mustache",
            )
        ).partial(
            events=cls._generate_events_prompt(team),
            groups=cls._retrieve_group_types(team),
        )

        toolkit = TrendsAgentToolkit(team)
        output_parser = ReActJsonSingleInputOutputParser()
        merger = merge_message_runs()

        agent = (
            RunnablePassthrough.assign(
                agent_scratchpad=lambda x: format_log_to_str(x["intermediate_steps"]),
            )
            | prompt
            | merger
            | llm_gpt_4o
            | output_parser
        )

        try:
            result = cast(
                Union[AgentAction, AgentFinish],
                agent.invoke(
                    {
                        "tools": toolkit.render_text_description(),
                        "tool_names": ", ".join([t["name"] for t in toolkit.tools]),
                        "intermediate_steps": intermediate_steps,
                    }
                ),
            )
        except OutputParserException:
            # incorrect json returned
            pass

        if isinstance(result, AgentFinish):
            # Exceptional case
            return state

        return {
            **state,
            "agent_state": {
                "intermediate_steps": [*intermediate_steps, (result, None)],
            },
        }


class CreateTrendsPlanToolsNode(AssistantNode):
    name = AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS

    @classmethod
    def run(cls, state: AssistantState) -> AssistantState:
        team = state["team"]
        if "agent_state" not in state or state["agent_state"] is None:
            raise ValueError("Invalid state.")

        toolkit = TrendsAgentToolkit(team)
        intermediate_steps = state["agent_state"]["intermediate_steps"]
        action, _ = intermediate_steps[-1]

        try:
            input = TrendsAgentToolModel(name=action.tool, argument=action.tool_input)
        except ValidationError as e:
            feedback = f"Invalid tool call. Pydantic exception: {e.errors(include_url=False)}"
            return {
                **state,
                "agent_state": {
                    "intermediate_steps": [*intermediate_steps, (action, feedback)],
                },
            }

        output = ""
        if input.name == "retrieve_entity_properties_tool":
            output = toolkit.retrieve_entity_properties(input.argument)
        elif input.name == "retrieve_event_properties_tool":
            output = toolkit.retrieve_event_properties(input.argument)
        else:
            output = toolkit.retrieve_property_values_tool(input.argument)

        return {
            **state,
            "agent_state": {
                "intermediate_steps": [*intermediate_steps[:-1], (action, output)],
            },
        }


class GenerateTrendsNode(AssistantNode):
    name = AssistantNodeName.GENERATE_TRENDS

    @classmethod
    def run(cls, state: AssistantState) -> AssistantState:
        return state
