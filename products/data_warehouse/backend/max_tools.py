from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing import Optional
from asgiref.sync import async_to_sync
from ee.hogai.graph.schema_generator.parsers import parse_pydantic_structured_output
from ee.hogai.graph.schema_generator.utils import SchemaGeneratorOutput
from ee.hogai.graph.sql.mixins import HogQLGeneratorMixin
from ee.hogai.tool import MaxTool
from products.data_warehouse.backend.prompts import (
    HOGQL_GENERATOR_USER_PROMPT,
    SQL_ASSISTANT_ROOT_SYSTEM_PROMPT,
)
from ee.hogai.graph.query_planner.prompts import PROPERTY_FILTERS_EXPLANATION_PROMPT
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.agent import TaxonomyAgent
from ee.hogai.graph.taxonomy.tools import base_final_answer
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState
from posthog.models import Team, User
from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException


class HogQLGeneratorArgs(BaseModel):
    instructions: str = Field(description="The instructions for what query to generate.")


class FinalAnswerArgs(SchemaGeneratorOutput[str]):
    pass


class final_answer(base_final_answer[FinalAnswerArgs]):
    __doc__ = "Use this tool to output the final SQL query ready to be executed."


class HogQLGeneratorToolkit(TaxonomyAgentToolkit):
    def __init__(self, team: Team):
        super().__init__(team)

    def _get_custom_tools(self) -> list:
        """Get custom tools for the HogQLGenerator."""

        return [final_answer]

    def _format_properties(self, props: list[tuple[str, str | None, str | None]]) -> str:
        """
        Override parent implementation to use YAML format instead of XML.
        """
        return self._format_properties_yaml(props)


class HogQLGeneratorNode(
    TaxonomyAgentNode[TaxonomyAgentState, TaxonomyAgentState[FinalAnswerArgs]], HogQLGeneratorMixin
):
    def __init__(self, team: Team, user: User, toolkit_class: HogQLGeneratorToolkit):
        super().__init__(team, user, toolkit_class=toolkit_class)

    def _get_system_prompt(self) -> ChatPromptTemplate:
        """Get default system prompts. Override in subclasses for custom prompts."""

        all_messages = [
            *super()._get_default_system_prompts(),
        ]
        system_messages = [("system", message) for message in all_messages]
        return ChatPromptTemplate(system_messages, template_format="mustache")

    def _construct_messages(self, state: TaxonomyAgentState) -> ChatPromptTemplate:
        """
        Overriding the parent method to handle async system prompt construction.
        """

        # Get the async system prompt
        system_prompt = async_to_sync(self._construct_system_prompt)()

        # Create combined system messages, preserving the original taxonomy system prompt structure
        taxonomy_system_messages = [("system", message) for message in super()._get_default_system_prompts()]

        combined_messages = [
            *system_prompt.messages,
            ("system", PROPERTY_FILTERS_EXPLANATION_PROMPT),
            *taxonomy_system_messages,
            ("human", state.change or ""),
            *(state.tool_progress_messages or []),
        ]

        # Create the final prompt template, preserving partial variables from the async system prompt
        return ChatPromptTemplate(
            combined_messages, template_format="mustache", partial_variables=system_prompt.partial_variables
        )


class HogQLGeneratorToolsNode(TaxonomyAgentToolsNode[TaxonomyAgentState, TaxonomyAgentState[FinalAnswerArgs]]):
    def __init__(self, team: Team, user: User, toolkit_class: HogQLGeneratorToolkit):
        super().__init__(team, user, toolkit_class=toolkit_class)


class HogQLGeneratorGraph(TaxonomyAgent[TaxonomyAgentState, TaxonomyAgentState[FinalAnswerArgs]]):
    def __init__(self, team: Team, user: User):
        super().__init__(
            team,
            user,
            loop_node_class=HogQLGeneratorNode,
            tools_node_class=HogQLGeneratorToolsNode,
            toolkit_class=HogQLGeneratorToolkit,
        )


class HogQLGeneratorTool(MaxTool, HogQLGeneratorMixin):
    name: str = "generate_hogql_query"
    description: str = (
        "Write or edit an SQL query to answer the user's question, and apply it to the current SQL editor"
    )
    thinking_message: str = "Coming up with an SQL query"
    args_schema: type[BaseModel] = HogQLGeneratorArgs
    root_system_prompt_template: str = SQL_ASSISTANT_ROOT_SYSTEM_PROMPT
    show_tool_call_message: bool = False

    async def _arun_impl(self, instructions: str) -> tuple[str, str]:
        current_query: str | None = self.context.get("current_query", "")
        user_prompt = HOGQL_GENERATOR_USER_PROMPT.format(instructions=instructions, current_query=current_query)

        graph = HogQLGeneratorGraph(team=self._team, user=self._user).compile_full_graph()

        graph_context = {
            "change": user_prompt,
            "output": None,
            "tool_progress_messages": [],
            **self.context,
        }

        final_error: Optional[Exception] = None
        for _ in range(3):
            try:
                result = await graph.ainvoke(graph_context)
                if result.get("intermediate_steps"):
                    if result["intermediate_steps"][-1]:
                        return result["intermediate_steps"][-1][0].tool_input, ""
                    else:
                        return "I need more information to generate the query.", ""
                else:
                    result = await self._parse_output(FinalAnswerArgs.model_validate(result["output"]))
                    return "```sql\n" + result + "\n```", result

            except PydanticOutputParserException as e:
                graph_context["change"] += f"\n\nAvoid this error: {str(e)}"
                final_error = e
        else:
            assert final_error is not None
            raise final_error

    async def _parse_output(self, output: dict) -> str:
        result = parse_pydantic_structured_output(SchemaGeneratorOutput[str])(output)  # type: ignore
        database = await self._get_database()
        hogql_context = self._get_default_hogql_context(database)
        query = await self._parse_generated_hogql(result.query, hogql_context)
        return query
