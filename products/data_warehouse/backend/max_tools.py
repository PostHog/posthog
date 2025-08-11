import json
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

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


class FinalAnswerArgs(SchemaGeneratorOutput[str]):
    pass


class HogQLGeneratorOptionsToolkit(TaxonomyAgentToolkit):
    def __init__(self, team: Team):
        super().__init__(team)

    def _get_custom_tools(self) -> list:
        """Get custom tools for filter options."""

        class final_answer(base_final_answer[FinalAnswerArgs]):
            __doc__ = "Outputs the final SQL query ready to be executed."

        return [final_answer]

    def _format_properties(self, props: list[tuple[str, str | None, str | None]]) -> str:
        """
        Override parent implementation to use YAML format instead of XML.
        """
        return self._format_properties_yaml(props)


class HogQLGeneratorNode(
    TaxonomyAgentNode[TaxonomyAgentState, TaxonomyAgentState[FinalAnswerArgs]], HogQLGeneratorMixin
):
    """Node for generating filtering options for session replay."""

    def __init__(self, team: Team, user: User, toolkit_class: HogQLGeneratorOptionsToolkit):
        super().__init__(team, user, toolkit_class=toolkit_class)

    def _get_system_prompt(self) -> ChatPromptTemplate:
        """Get default system prompts. Override in subclasses for custom prompts."""
        # This is a fallback that returns basic prompts - the async version is used in arun
        all_messages = [
            *super()._get_default_system_prompts(),
        ]
        system_messages = [("system", message) for message in all_messages]
        return ChatPromptTemplate(system_messages, template_format="mustache")

    def _construct_messages(self, state: TaxonomyAgentState) -> ChatPromptTemplate:
        """
        Override parent method to handle async system prompt construction.
        """
        import asyncio

        # Get the async system prompt using sync_to_async
        async def get_system_prompt():
            return await self._construct_system_prompt()

        system_prompt = asyncio.run(get_system_prompt())

        # Create combined system messages, preserving the original system prompt structure
        parent_system_messages = [("system", message) for message in super()._get_default_system_prompts()]

        # Combine the messages from the async system prompt with parent messages
        combined_messages = [
            *system_prompt.messages,
            ("system", PROPERTY_FILTERS_EXPLANATION_PROMPT),
            *parent_system_messages,
            ("human", state.change or ""),
            *(state.tool_progress_messages or []),
        ]

        # Create the final prompt template, preserving partial variables from system_prompt
        return ChatPromptTemplate(
            combined_messages, template_format="mustache", partial_variables=system_prompt.partial_variables
        )


class HogQLGeneratorOptionsToolsNode(TaxonomyAgentToolsNode[TaxonomyAgentState, TaxonomyAgentState[FinalAnswerArgs]]):
    """Node for generating filtering options for session replay."""

    def __init__(self, team: Team, user: User, toolkit_class: HogQLGeneratorOptionsToolkit):
        super().__init__(team, user, toolkit_class=toolkit_class)


class HogQLGeneratorOptionsGraph(TaxonomyAgent[TaxonomyAgentState, TaxonomyAgentState[FinalAnswerArgs]]):
    """Graph for generating filtering options for session replay."""

    def __init__(self, team: Team, user: User):
        super().__init__(
            team,
            user,
            loop_node_class=HogQLGeneratorNode,
            tools_node_class=HogQLGeneratorOptionsToolsNode,
            toolkit_class=HogQLGeneratorOptionsToolkit,
        )


class HogQLGeneratorArgs(BaseModel):
    instructions: str = Field(description="The instructions for what query to generate.")


class HogQLGeneratorTool(MaxTool, HogQLGeneratorMixin):
    name: str = "generate_hogql_query"
    description: str = (
        "Write or edit an SQL query to answer the user's question, and apply it to the current SQL editor"
    )
    thinking_message: str = "Coming up with an SQL query"
    args_schema: type[BaseModel] = HogQLGeneratorArgs
    root_system_prompt_template: str = SQL_ASSISTANT_ROOT_SYSTEM_PROMPT

    async def _arun_impl(self, instructions: str) -> tuple[str, str]:
        current_query: str | None = self.context.get("current_query", "")
        # system_prompt = await self._construct_system_prompt()

        pretty_filters = json.dumps(current_query, indent=2)
        user_prompt = HOGQL_GENERATOR_USER_PROMPT.format(instructions=instructions, current_query=pretty_filters)

        graph = HogQLGeneratorOptionsGraph(team=self._team, user=self._user)

        graph_context = {
            "change": user_prompt,
            "output": None,
            "tool_progress_messages": [],
            **self.context,
        }

        result = await graph.compile_full_graph().ainvoke(graph_context)

        # final_error: Optional[Exception] = None
        # for _ in range(3):
        #     try:
        #         chain = prompt | merge_message_runs | self._model | self._parse_output
        #         result: str = await chain.ainvoke(
        #             {
        #                 "current_query": current_query,
        #                 "instructions": instructions,
        #             }
        #         )
        #         break
        #     except PydanticOutputParserException as e:
        #         prompt += f"Avoid this error: {str(e)}"
        #         final_error = e
        # else:
        #     assert final_error is not None
        #     raise final_error

        if result.get("intermediate_steps"):
            result = result["intermediate_steps"][-1][0].tool_input
            return result, ""
        else:
            result = await self._parse_output(FinalAnswerArgs.model_validate(result["output"]))
            return "```sql\n" + result + "\n```", result

    async def _parse_output(self, output: dict) -> str:
        result = parse_pydantic_structured_output(SchemaGeneratorOutput[str])(output)  # type: ignore
        database = await self._get_database()
        hogql_context = self._get_default_hogql_context(database)
        query = await self._parse_generated_hogql(result.query, hogql_context)
        return query
