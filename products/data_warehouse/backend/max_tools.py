from typing import Optional, cast

from asgiref.sync import async_to_sync
from langchain_core.prompts import ChatPromptTemplate
from posthoganalytics import capture_exception
from pydantic import BaseModel, Field

from posthog.schema import AssistantHogQLQuery

from posthog.models import Team, User

from products.data_warehouse.backend.prompts import (
    HOGQL_GENERATOR_USER_PROMPT,
    SQL_ASSISTANT_ROOT_SYSTEM_PROMPT,
    TIME_PERIOD_PROMPT,
)

from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.graph.schema_generator.utils import SchemaGeneratorOutput
from ee.hogai.graph.sql.mixins import HogQLGeneratorMixin
from ee.hogai.graph.taxonomy.agent import TaxonomyAgent
from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.graph.taxonomy.tools import base_final_answer
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState
from ee.hogai.tool import MaxTool


class HogQLGeneratorArgs(BaseModel):
    instructions: str = Field(description="The instructions for what query to generate.")


class FinalAnswerArgs(SchemaGeneratorOutput[str]):
    pass


class final_answer(base_final_answer[FinalAnswerArgs]):
    __doc__ = "Use this tool to output the final SQL query ready to be executed."


class HogQLGeneratorToolkit(TaxonomyAgentToolkit):
    def __init__(self, team: Team, user: User):
        super().__init__(team, user)

    def _get_custom_tools(self) -> list:
        """Get custom tools for the HogQLGenerator."""

        return [final_answer]

    def _format_properties(self, props: list[tuple[str, str | None, str | None]]) -> str:
        """
        Override parent implementation to use YAML format instead of XML.
        """
        return self._format_properties_yaml(props)


GENERATION_ATTEMPTS_ALLOWED = 3


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
            *taxonomy_system_messages,
            ("system", TIME_PERIOD_PROMPT),
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


class HogQLGeneratorTool(HogQLGeneratorMixin, MaxTool):
    name: str = "generate_hogql_query"
    description: str = "Write or edit an SQL query to answer the user's question, and apply it to the current SQL editor only include the current change the user requested"
    args_schema: type[BaseModel] = HogQLGeneratorArgs
    context_prompt_template: str = SQL_ASSISTANT_ROOT_SYSTEM_PROMPT

    async def _arun_impl(self, instructions: str) -> tuple[str, str]:
        current_query: str | None = self.context.get("current_query", "")
        user_prompt = HOGQL_GENERATOR_USER_PROMPT.format(instructions=instructions, current_query=current_query)

        graph = HogQLGeneratorGraph(team=self._team, user=self._user).compile_full_graph()

        graph_context = {
            "change": user_prompt,
            "output": None,
            "tool_progress_messages": [],
            "billable": True,
            **self.context,
        }

        final_result: SchemaGeneratorOutput[AssistantHogQLQuery] | None = None
        final_error: Optional[PydanticOutputParserException] = None
        for _ in range(GENERATION_ATTEMPTS_ALLOWED):
            try:
                result_so_far = await graph.ainvoke(graph_context)
                if result_so_far.get("intermediate_steps"):
                    if result_so_far["intermediate_steps"][-1]:
                        return result_so_far["intermediate_steps"][-1][0].tool_input, ""
                    else:
                        return "I need more information to generate the query.", ""
                else:
                    output = result_so_far["output"]
                    assert output is not None
                    final_result = self._parse_output(output)
                    # If quality check raises, we will still iterate if we've got any attempts left,
                    # however if we don't have any more attempts, we're okay to use `resulting_query` (instead of throwing)
                    await self._quality_check_output(
                        output=final_result,
                    )
                    final_error = None
                    break  # All good, let's go
            except PydanticOutputParserException as e:
                graph_context["change"] += f"\n\nAvoid this error that we had with our previous attempt:\n\n{str(e)}"
                final_error = e

        if not final_result:
            raise cast(Exception, final_error)  # We haven't managed to create valid query JSON even once

        if final_error is not None:
            # We've got some result but the last time still had some syntactic issue (_validate_hogql() raised)
            # Well, better that that nothing - let's just capture the error and send what we've got
            capture_exception(final_error)

        return "```sql\n" + final_result.query.query + "\n```", final_result.query.query
