import itertools
import json
import xml.etree.ElementTree as ET
from functools import cached_property
from typing import Optional, Union, cast

from langchain.agents.format_scratchpad import format_log_to_str
from langchain.agents.output_parsers import ReActJsonSingleInputOutputParser
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage as LangchainAssistantMessage
from langchain_core.messages import BaseMessage, merge_message_runs
from langchain_core.messages import HumanMessage as LangchainHumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from ee.hogai.hardcoded_definitions import hardcoded_prop_defs
from ee.hogai.trends.prompts import (
    react_definitions_prompt,
    react_follow_up_prompt,
    react_scratchpad_prompt,
    react_system_prompt,
    react_user_prompt,
    trends_failover_prompt,
    trends_group_mapping_prompt,
    trends_new_plan_prompt,
    trends_plan_prompt,
    trends_question_prompt,
    trends_system_prompt,
)
from ee.hogai.trends.toolkit import (
    GenerateTrendTool,
    TrendsAgentToolkit,
    TrendsAgentToolModel,
)
from ee.hogai.trends.utils import GenerateTrendOutputModel
from ee.hogai.utils import (
    AssistantNode,
    AssistantNodeName,
    AssistantState,
    remove_line_breaks,
)
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.schema import CachedTeamTaxonomyQueryResponse, HumanMessage, TeamTaxonomyQuery, VisualizationMessage


class CreateTrendsPlanNode(AssistantNode):
    name = AssistantNodeName.CREATE_TRENDS_PLAN

    def run(self, state: AssistantState, config: RunnableConfig):
        intermediate_steps = state.get("intermediate_steps") or []

        prompt = (
            ChatPromptTemplate.from_messages(
                [
                    ("system", react_system_prompt),
                    ("user", react_definitions_prompt),
                ],
                template_format="mustache",
            )
            + self._reconstruct_conversation(state)
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

        agent = prompt | merger | self._model | output_parser

        try:
            result = cast(
                Union[AgentAction, AgentFinish],
                agent.invoke(
                    {
                        "tools": toolkit.render_text_description(),
                        "tool_names": ", ".join([t["name"] for t in toolkit.tools]),
                        "agent_scratchpad": format_log_to_str(
                            [(action, output) for action, output in intermediate_steps if output is not None]
                        ),
                    },
                    config,
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

    def router(self, state: AssistantState):
        if state.get("plan") is not None:
            return AssistantNodeName.GENERATE_TRENDS

        if state.get("intermediate_steps", []):
            return AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS

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

        events: list[str] = []
        for item in response.results:
            if len(response.results) > 25 and item.count <= 3:
                continue
            events.append(item.event)

        # default for null in the
        tags: list[str] = ["all events"]

        for event_name in events:
            event_tag = event_name
            if event_name in hardcoded_prop_defs["events"]:
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

    def _reconstruct_conversation(self, state: AssistantState) -> list[BaseMessage]:
        """
        Reconstruct the conversation for the agent. On this step we only care about previously asked questions and generated plans. All other messages are filtered out.
        """
        messages = state.get("messages", [])
        if len(messages) == 0:
            return []

        conversation = [
            HumanMessagePromptTemplate.from_template(react_user_prompt, template_format="mustache").format(
                question=messages[0].content if isinstance(messages[0], HumanMessage) else ""
            )
        ]

        for message in messages[1:]:
            if isinstance(message, HumanMessage):
                conversation.append(
                    HumanMessagePromptTemplate.from_template(
                        react_follow_up_prompt,
                        template_format="mustache",
                    ).format(feedback=message.content)
                )
            elif isinstance(message, VisualizationMessage):
                conversation.append(LangchainAssistantMessage(content=message.plan or ""))

        return conversation


class CreateTrendsPlanToolsNode(AssistantNode):
    name = AssistantNodeName.CREATE_TRENDS_PLAN_TOOLS

    def run(self, state: AssistantState, config: RunnableConfig):
        toolkit = TrendsAgentToolkit(self._team)
        intermediate_steps = state.get("intermediate_steps") or []
        action, _ = intermediate_steps[-1]

        try:
            input = TrendsAgentToolModel.model_validate({"name": action.tool, "arguments": action.tool_input}).root
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

        return {"intermediate_steps": [*intermediate_steps[:-1], (action, output)]}

    def router(self, state: AssistantState):
        if state.get("plan") is not None:
            return AssistantNodeName.GENERATE_TRENDS
        return AssistantNodeName.CREATE_TRENDS_PLAN


class GenerateTrendsNode(AssistantNode):
    name = AssistantNodeName.GENERATE_TRENDS

    def run(self, state: AssistantState, config: RunnableConfig):
        generated_plan = state.get("plan", "")
        intermediate_steps = state.get("intermediate_steps", [])
        validation_error_message = intermediate_steps[-1][1] if intermediate_steps else None

        trends_generation_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", trends_system_prompt),
            ],
            template_format="mustache",
        ) + self._reconstruct_conversation(state, validation_error_message=validation_error_message)
        merger = merge_message_runs()

        chain = (
            trends_generation_prompt
            | merger
            | self._model
            # Result from structured output is a parsed dict. Convert to a string since the output parser expects it.
            | RunnableLambda(lambda x: json.dumps(x))
            # Validate a string input.
            | PydanticOutputParser[GenerateTrendOutputModel](pydantic_object=GenerateTrendOutputModel)
        )

        try:
            message: GenerateTrendOutputModel = chain.invoke({}, config)
        except OutputParserException as e:
            if e.send_to_llm:
                observation = str(e.observation)
            else:
                observation = "Invalid or incomplete response. You must use the provided tools and output JSON to answer the user's question."

            return {
                "intermediate_steps": [(AgentAction("handle_incorrect_response", observation, str(e)), None)],
            }

        return {
            "messages": [
                VisualizationMessage(
                    plan=generated_plan,
                    reasoning_steps=message.reasoning_steps,
                    answer=message.answer,
                )
            ],
            "intermediate_steps": None,
        }

    def router(self, state: AssistantState):
        if state.get("intermediate_steps") is not None:
            return AssistantNodeName.GENERATE_TRENDS_TOOLS
        return AssistantNodeName.END

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4o", temperature=0.2, streaming=True).with_structured_output(
            GenerateTrendTool().schema,
            method="function_calling",
            include_raw=False,
        )

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

    def _reconstruct_conversation(
        self, state: AssistantState, validation_error_message: Optional[str] = None
    ) -> list[BaseMessage]:
        """
        Reconstruct the conversation for the generation. Take all previously generated questions, plans, and schemas, and return the history.
        """
        messages = state.get("messages", [])
        generated_plan = state.get("plan", "")

        if len(messages) == 0:
            return []

        conversation: list[BaseMessage] = [
            HumanMessagePromptTemplate.from_template(trends_group_mapping_prompt, template_format="mustache").format(
                group_mapping=self._group_mapping_prompt
            )
        ]

        stack: list[LangchainHumanMessage] = []
        human_messages: list[LangchainHumanMessage] = []
        visualization_messages: list[VisualizationMessage] = []

        for message in messages:
            if isinstance(message, HumanMessage):
                stack.append(LangchainHumanMessage(content=message.content))
            elif isinstance(message, VisualizationMessage) and message.answer:
                if stack:
                    human_messages += merge_message_runs(stack)
                    stack = []
                visualization_messages.append(message)

        if stack:
            human_messages += merge_message_runs(stack)

        first_ai_message = True

        for human_message, ai_message in itertools.zip_longest(human_messages, visualization_messages):
            if ai_message:
                conversation.append(
                    HumanMessagePromptTemplate.from_template(
                        trends_plan_prompt if first_ai_message else trends_new_plan_prompt,
                        template_format="mustache",
                    ).format(plan=ai_message.plan or "")
                )
                first_ai_message = False
            elif generated_plan:
                conversation.append(
                    HumanMessagePromptTemplate.from_template(
                        trends_plan_prompt if first_ai_message else trends_new_plan_prompt,
                        template_format="mustache",
                    ).format(plan=generated_plan)
                )

            if human_message:
                conversation.append(
                    HumanMessagePromptTemplate.from_template(trends_question_prompt, template_format="mustache").format(
                        question=human_message.content
                    )
                )

            if ai_message:
                conversation.append(
                    LangchainAssistantMessage(content=ai_message.answer.model_dump_json() if ai_message.answer else "")
                )

        if validation_error_message:
            conversation.append(
                HumanMessagePromptTemplate.from_template(trends_failover_prompt, template_format="mustache").format(
                    exception_message=validation_error_message
                )
            )

        return conversation

    @classmethod
    def parse_output(cls, output: dict):
        try:
            return GenerateTrendOutputModel.model_validate(output)
        except ValidationError:
            return None


class GenerateTrendsToolsNode(AssistantNode):
    """
    Used for failover from generation errors.
    """

    name = AssistantNodeName.GENERATE_TRENDS_TOOLS

    def run(self, state: AssistantState, config: RunnableConfig):
        intermediate_steps = state.get("intermediate_steps", [])
        if not intermediate_steps:
            return state
        action, _ = intermediate_steps[-1]
        return {"intermediate_steps": [(action, action.log)]}
