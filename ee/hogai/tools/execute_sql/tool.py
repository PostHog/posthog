from typing import Self

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from posthog.models import Team, User

from products.data_warehouse.backend.prompts import SQL_ASSISTANT_ROOT_SYSTEM_PROMPT

from ee.hogai.context import AssistantContextManager
from ee.hogai.graph.query_executor.query_executor import QueryExecutorError, execute_and_format_query
from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.graph.sql.mixins import HogQLGeneratorMixin
from ee.hogai.graph.sql.prompts import (
    SQL_EXPRESSIONS_DOCS,
    SQL_SUPPORTED_AGGREGATIONS_DOCS,
    SQL_SUPPORTED_FUNCTIONS_DOCS,
)
from ee.hogai.tool import MaxTool

# from ee.hogai.graph.sql.prompts import
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath

from .prompts import (
    EXECUTE_SQL_RECOVERABLE_ERROR_PROMPT,
    EXECUTE_SQL_SYSTEM_PROMPT,
    EXECUTE_SQL_UNRECOVERABLE_ERROR_PROMPT,
)


class ExecuteSQLToolArgs(BaseModel):
    query: str = Field(description="The final SQL query to be executed.")


class ExecuteSQLTool(HogQLGeneratorMixin, MaxTool):
    name: str = "execute_sql"
    thinking_message: str = "Coming up with an SQL query"
    args_schema: type[BaseModel] = ExecuteSQLToolArgs
    context_prompt_template: str = SQL_ASSISTANT_ROOT_SYSTEM_PROMPT
    show_tool_call_message: bool = False

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...] | None = None,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
        context_manager: AssistantContextManager | None = None,
    ) -> Self:
        prompt = format_prompt_string(
            EXECUTE_SQL_SYSTEM_PROMPT,
            sql_expressions_docs=SQL_EXPRESSIONS_DOCS,
            sql_supported_functions_docs=SQL_SUPPORTED_FUNCTIONS_DOCS,
            sql_supported_aggregations_docs=SQL_SUPPORTED_AGGREGATIONS_DOCS,
        )
        return cls(team=team, user=user, state=state, config=config, description=prompt)

    async def _arun_impl(self, query: str) -> tuple[str, str]:
        parsed_query = self._parse_output({"query": query})
        try:
            await self._quality_check_output(
                output=parsed_query,
            )
        except PydanticOutputParserException as e:
            return format_prompt_string(EXECUTE_SQL_RECOVERABLE_ERROR_PROMPT, error=str(e)), ""

        try:
            result = await execute_and_format_query(self._team, parsed_query.query)
        except QueryExecutorError as e:
            return format_prompt_string(EXECUTE_SQL_RECOVERABLE_ERROR_PROMPT, error=str(e)), ""
        except:
            return EXECUTE_SQL_UNRECOVERABLE_ERROR_PROMPT, ""

        return result, parsed_query.query.query
