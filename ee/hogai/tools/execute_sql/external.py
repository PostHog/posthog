from typing import Any

from pydantic import BaseModel, Field

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.chat_agent.sql.mixins import HogQLOutputParserMixin
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.external_tool import MCPTool, mcp_tool_registry
from ee.hogai.tool_errors import MaxToolRetryableError


class ExecuteSQLExternalToolArgs(BaseModel):
    query: str = Field(description="The final SQL query to be executed.")


@mcp_tool_registry.register(scopes=["insight:read", "query:read"])
class ExecuteSQLMCPTool(HogQLOutputParserMixin, MCPTool[ExecuteSQLExternalToolArgs]):
    """
    MCP version of ExecuteSQLTool.

    Executes HogQL queries without LangChain context or artifact creation.
    """

    name = "execute_sql"
    args_schema = ExecuteSQLExternalToolArgs

    async def execute(self, args: ExecuteSQLExternalToolArgs) -> tuple[str, dict[str, Any] | None]:
        try:
            validated_query = await self._validate_hogql_query(args.query)
        except PydanticOutputParserException as e:
            raise MaxToolRetryableError(f"Query validation failed: {e.validation_message}")

        insight_context = InsightContext(
            team=self._team,
            query=validated_query,
            name="",
            description="",
        )
        result = await insight_context.execute_and_format()

        return result, {"query": args.query}
