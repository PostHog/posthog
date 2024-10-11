import json
import xml.etree.ElementTree as ET
from functools import cached_property
from typing import Union, cast

from langchain.agents.format_scratchpad import format_log_to_str
from langchain.agents.output_parsers import ReActJsonSingleInputOutputParser
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, merge_message_runs
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from pydantic import ValidationError

from ee.hogai.hardcoded_definitions import hardcoded_prop_defs
from ee.hogai.trends.prompts import (
    react_definitions_prompt,
    react_scratchpad_prompt,
    react_system_prompt,
    trends_system_prompt,
    trends_user_prompt,
)
from ee.hogai.trends.toolkit import (
    GenerateTrendOutputModel,
    GenerateTrendTool,
    TrendsAgentToolkit,
    TrendsAgentToolModel,
)
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
from posthog.schema import CachedTeamTaxonomyQueryResponse, TeamTaxonomyQuery


class CreateTrendsPlanNode(AssistantNode):
    name = AssistantNodeName.CREATE_TRENDS_PLAN

    @cached_property
    def _events_prompt(self) -> str:
        event_description_mapping = {
            "$identify": "Identifies an anonymous user. This event doesn't show how many users you have but rather how many users used an account."
        }

        response = TeamTaxonomyQueryRunner(TeamTaxonomyQuery(), self._team).run(
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

    @cached_property
    def _team_group_types(self) -> list[str]:
        return list(
            GroupTypeMapping.objects.filter(team=self._team)
            .order_by("group_type_index")
            .values_list("group_type", flat=True)
        )

    def router(self, state: AssistantState):
        # Exceptional case. TODO: decide how to handle this.
        if state.get("plan") is not None:
            return AssistantNodeName.GENERATE_TRENDS

        if state.get("intermediate_steps", []):
            return AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS

        raise ValueError("Invalid state.")

    def run(self, state: AssistantState):
        intermediate_steps = state.get("intermediate_steps") or []

        prompt = (
            ChatPromptTemplate.from_messages(
                [
                    ("system", react_system_prompt),
                    ("user", react_definitions_prompt),
                ],
                template_format="mustache",
            )
            + state["messages"]
            + ChatPromptTemplate.from_messages(
                [
                    ("user", react_scratchpad_prompt),
                ],
                template_format="mustache",
            )
        ).partial(
            events=self._events_prompt,
            groups=self._team_group_types,
        )

        toolkit = TrendsAgentToolkit(self._team)
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
        except OutputParserException as e:
            text = str(e)
            if e.send_to_llm:
                observation = str(e.observation)
                text = str(e.llm_output)
            else:
                observation = "Invalid or incomplete response. You must use the provided tools and output JSON to answer the user's question."
            result = AgentAction("handle_incorrect_response", observation, text)

        if isinstance(result, AgentFinish):
            # Exceptional case
            return {
                "plan": result.log,
                "intermediate_steps": None,
            }

        return {
            "intermediate_steps": [*intermediate_steps, (result, None)],
        }


class CreateTrendsPlanToolsNode(AssistantNode):
    name = AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS

    def router(self, state: AssistantState):
        if state.get("plan") is not None:
            return AssistantNodeName.GENERATE_TRENDS
        return AssistantNodeName.CREATE_TRENDS_PLAN

    def run(self, state: AssistantState):
        toolkit = TrendsAgentToolkit(self._team)
        intermediate_steps = state.get("intermediate_steps") or []
        action, _ = intermediate_steps[-1]

        try:
            input = TrendsAgentToolModel(name=action.tool, arguments=action.tool_input).root
        except ValidationError as e:
            feedback = f"Invalid tool call. Pydantic exception: {e.errors(include_url=False)}"
            return {"intermediate_steps": [*intermediate_steps, (action, feedback)]}

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

        return {"intermediate_steps": [*intermediate_steps, (action, output)]}


class GenerateTrendsNode(AssistantNode):
    name = AssistantNodeName.GENERATE_TRENDS

    @cached_property
    def _group_mapping_prompt(self) -> str:
        groups = GroupTypeMapping.objects.filter(team=self._team).order_by("group_type_index")
        if not groups:
            return "The user has not defined any groups."

        root = ET.Element("list of defined groups")
        root.text = (
            "\n" + "\n".join([f'name "{group.group_type}", index {group.group_type_index}' for group in groups]) + "\n"
        )
        return ET.tostring(root, encoding="unicode")

    def router(self, state: AssistantState):
        if state.get("tool_argument") is not None:
            return AssistantNodeName.GENERATE_TRENDS_TOOLS
        return AssistantNodeName.END

    def run(self, state: AssistantState):
        user_message = state["messages"][-1]

        llm = llm_gpt_4o.with_structured_output(
            GenerateTrendTool().schema,
            method="function_calling",
            include_raw=False,
        )

        trends_generation_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", trends_system_prompt),
                ("user", trends_user_prompt),
            ],
            template_format="mustache",
        ).partial(
            plan=state.get("plan", ""),
            question=user_message.content,
        )

        chain = (
            trends_generation_prompt
            | llm
            | RunnableLambda(lambda x: json.dumps(x))
            | PydanticOutputParser[GenerateTrendOutputModel](pydantic_object=GenerateTrendOutputModel)
            | RunnableLambda(lambda x: x.model_dump_json())
        )

        try:
            message = chain.invoke({"group_mapping": self._group_mapping_prompt})
        except OutputParserException as e:
            if e.send_to_llm:
                observation = str(e.observation)
            else:
                observation = "Invalid or incomplete response. You must use the provided tools and output JSON to answer the user's question."
            return {"tool_argument": observation}

        return {"messages": [AIMessage(content=message)]}


class GenerateTrendsToolsNode(AssistantNode):
    """
    Used for failover from generation errors.
    """

    name = AssistantNodeName.GENERATE_TRENDS_TOOLS

    def run(self, state: AssistantState):
        return state
