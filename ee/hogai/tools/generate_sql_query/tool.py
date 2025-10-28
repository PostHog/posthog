from typing import Self

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from posthog.models import Team, User

from products.data_warehouse.backend.prompts import SQL_ASSISTANT_ROOT_SYSTEM_PROMPT

from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.graph.sql.mixins import HogQLGeneratorMixin
from ee.hogai.graph.sql.prompts import (
    SQL_EXPRESSIONS_DOCS,
    SQL_SUPPORTED_AGGREGATIONS_DOCS,
    SQL_SUPPORTED_FUNCTIONS_DOCS,
)
from ee.hogai.tool import MaxTool
from ee.hogai.tools.generate_sql_query.prompts import (
    GENERATE_SQL_QUERY_ERROR_PROMPT,
    GENERATE_SQL_QUERY_SUCCESS_RESPONSE,
    GENERATE_SQL_QUERY_SYSTEM_PROMPT,
)

# from ee.hogai.graph.sql.prompts import
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types import AssistantState


class GenerateSQLQueryToolArgs(BaseModel):
    query: str = Field(description="The final SQL query to be executed.")


class GenerateSQLQueryTool(HogQLGeneratorMixin, MaxTool):
    name: str = "generate_sql_query"
    thinking_message: str = "Coming up with an SQL query"
    args_schema: type[BaseModel] = GenerateSQLQueryToolArgs
    context_prompt_template: str = SQL_ASSISTANT_ROOT_SYSTEM_PROMPT
    show_tool_call_message: bool = False

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
    ) -> Self:
        prompt = format_prompt_string(
            GENERATE_SQL_QUERY_SYSTEM_PROMPT,
            sql_expressions_docs=SQL_EXPRESSIONS_DOCS,
            sql_supported_functions_docs=SQL_SUPPORTED_FUNCTIONS_DOCS,
            sql_supported_aggregations_docs=SQL_SUPPORTED_AGGREGATIONS_DOCS,
        )
        return cls(team=team, user=user, state=state, config=config, description=prompt)

    async def _arun_impl(self, query: str) -> tuple[str, str]:
        final_result = self._parse_output(query)
        try:
            await self._quality_check_output(
                output=final_result,
            )
        except PydanticOutputParserException as e:
            return format_prompt_string(GENERATE_SQL_QUERY_ERROR_PROMPT, query=query, error=str(e)), ""

        return format_prompt_string(
            GENERATE_SQL_QUERY_SUCCESS_RESPONSE, query=final_result.query.query
        ), final_result.query.query
