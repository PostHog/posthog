from collections.abc import Sequence
from typing import Literal, Optional, Union

from langchain.agents import AgentOutputParser
from langchain.agents.format_scratchpad import format_log_to_str
from langchain.agents.output_parsers import ReActJsonSingleInputOutputParser, ReActSingleInputOutputParser
from langchain.callbacks.manager import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import merge_message_runs
from langchain_core.prompts import BasePromptTemplate, ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnablePassthrough
from langchain_core.tools import BaseTool
from langchain_core.tools.render import ToolsRenderer, render_text_description
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


def create_react_agent(
    llm: BaseLanguageModel,
    tools: Sequence[BaseTool],
    prompt: BasePromptTemplate,
    output_parser: Optional[AgentOutputParser] = None,
    tools_renderer: ToolsRenderer = render_text_description,
    *,
    stop_sequence: Union[bool, list[str]] = True,
) -> Runnable:
    missing_vars = {"tools", "tool_names", "agent_scratchpad"}.difference(
        prompt.input_variables + list(prompt.partial_variables)
    )
    if missing_vars:
        raise ValueError(f"Prompt missing required variables: {missing_vars}")

    prompt = prompt.partial(
        tools=tools_renderer(list(tools)),
        tool_names=", ".join([t.name for t in tools]),
    )
    if stop_sequence:
        stop = ["\nObservation"] if stop_sequence is True else stop_sequence
        llm_with_stop = llm.bind(stop=stop)
    else:
        llm_with_stop = llm
    output_parser = output_parser or ReActSingleInputOutputParser()
    merger = merge_message_runs()
    agent = (
        RunnablePassthrough.assign(
            agent_scratchpad=lambda x: format_log_to_str(x["intermediate_steps"]),
        )
        | prompt
        | merger
        | llm_with_stop
        | output_parser
    )
    return agent


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
    def run(cls, state: AssistantState) -> AssistantState:
        team = state["team"]
        messages = state["messages"]

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

        agent = (
            # RunnablePassthrough.assign(
            #     agent_scratchpad=lambda x: format_log_to_str(x["intermediate_steps"]),
            # )
            # |
            prompt | merger | llm_gpt_4o | output_parser
        )

        result = agent.invoke(
            {
                "tools": render_text_description(tools),
                "tool_names": ", ".join([t.name for t in tools]),
                "agent_scratchpad": "",
            }
        )

        return {
            **state,
            "messages": [result["output"]],
        }


class CreateTrendsPlanToolsNode(AssistantNode):
    name = AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS

    @classmethod
    def run(cls, state: AssistantState) -> AssistantState:
        return state


class GenerateTrendsNode(AssistantNode):
    name = AssistantNodeName.GENERATE_TRENDS

    @classmethod
    def run(cls, state: AssistantState) -> AssistantState:
        return state
