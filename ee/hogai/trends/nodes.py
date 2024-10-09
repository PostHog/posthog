from typing import Literal, Optional, Union, cast

from langchain.agents.output_parsers import ReActJsonSingleInputOutputParser
from langchain.callbacks.manager import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.messages import merge_message_runs
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import BaseTool
from langchain_core.tools.render import render_text_description
from pydantic import BaseModel, Field

from ee.hogai.hardcoded_definitions import hardcoded_prop_defs
from ee.hogai.trends.prompts import react_definitions_prompt, react_scratchpad_prompt, react_system_prompt
from ee.hogai.utils import (
    AssistantNode,
    AssistantNodeName,
    AssistantState,
    generate_xml_tag,
    llm_gpt_4o,
    remove_line_breaks,
)
from posthog.models.event_definition import EventDefinition
from posthog.models.team.team import Team


class RetrieveEntityTaxonomyArgs(BaseModel):
    entity: Literal["person", "session", "cohort", "organization", "instance", "project"] = Field(
        ..., description="The type of the entity that you want to retrieve properties for."
    )


class RetrieveEntityTaxonomyTool(BaseTool):
    name: str = "retrieve_entity_properties_tool"
    description: str = """
    Use this tool to retrieve property names for a property group (entity) that the user has in their taxonomy. You will receive a list of properties and their value types or a message that properties have not been found.

    - **Infer the property groups from the user's request.**
    - **Try other entities** if the tool doesn't return any properties.
    - **Prioritize properties that are directly related to the context or objective of the user's query.**
    - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.
    """
    args_schema: type[BaseModel] = RetrieveEntityTaxonomyArgs

    def _run(self, entity: str, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        return "LangChain"

    async def _arun(self, entity: str, run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        raise NotImplementedError("custom_search does not support async")


tools: list[BaseTool] = [RetrieveEntityTaxonomyTool()]


class CreateTrendsPlanNode(AssistantNode):
    name = AssistantNodeName.CREATE_TRENDS_PLAN

    @classmethod
    def _generate_events_prompt(cls, team: Team) -> str:
        event_description_mapping = {
            "$identify": "Identifies an anonymous user. This event doesn't show how many users you have but rather how many users used an account."
        }

        events = EventDefinition.objects.filter(team_id=team.pk).values_list("name", flat=True)

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

        tag_name = "list of available events for filtering"
        return generate_xml_tag(tag_name, "\n".join(tags)).strip()

    @classmethod
    def router(
        cls,
        state: AssistantState,
    ) -> Literal[AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS, AssistantNodeName.GENERATE_TRENDS]:
        # The plan was generated.
        if not state["agent_state"]:
            return AssistantNodeName.GENERATE_TRENDS

        # Invalid state
        if (
            state["agent_state"] is None
            or "intermediate_steps" not in state["agent_state"]
            or len(state["agent_state"]["intermediate_steps"]) == 0
            or state["agent_state"]["intermediate_steps"][-1][1] is not None
        ):
            raise ValueError("Invalid state.")

        return AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS

    @classmethod
    def run(cls, state: AssistantState) -> AssistantState:
        team = state["team"]
        messages = state["messages"]
        intermediate_steps = state["agent_state"]["intermediate_steps"] if state.get("agent_state") is not None else []

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
        )

        output_parser = ReActJsonSingleInputOutputParser()
        merger = merge_message_runs()

        agent = prompt | merger | llm_gpt_4o | output_parser

        result = cast(
            Union[AgentAction, AgentFinish],
            agent.invoke(
                {
                    "tools": render_text_description(tools),
                    "tool_names": ", ".join([t.name for t in tools]),
                    "agent_scratchpad": "",
                }
            ),
        )

        if isinstance(result, AgentFinish):
            # Exceptional case
            return {
                **state,
                "last_thought": result.output,
            }

        return {
            **state,
            "agent_state": {
                "intermediate_steps": [*intermediate_steps, (result, None)],
            },
        }


class GenerateTrendsNode(AssistantNode):
    name = AssistantNodeName.GENERATE_TRENDS

    @classmethod
    def run(cls, state: AssistantState) -> AssistantState:
        return state
