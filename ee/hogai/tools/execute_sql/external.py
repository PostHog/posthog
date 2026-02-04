from typing import Any

from pydantic import BaseModel, Field

from ee.hogai.external_tool import ExternalTool, register_external_tool
from ee.hogai.tool_errors import MaxToolRetryableError

from .core import HogQLValidationError, execute_hogql_query, validate_hogql


class ExecuteSQLExternalToolArgs(BaseModel):
    query: str = Field(description="The final SQL query to be executed.")


@register_external_tool(scopes=["insight:read", "query:read"])
class ExecuteSQLExternalTool(ExternalTool[ExecuteSQLExternalToolArgs]):
    """
    External version of ExecuteSQLTool for API/MCP callers.

    Executes HogQL queries without LangChain context or artifact creation.
    """

    name = "execute_sql"
    args_schema = ExecuteSQLExternalToolArgs

    async def execute(self, args: ExecuteSQLExternalToolArgs) -> tuple[str, dict[str, Any] | None]:
        try:
            validated_query = await validate_hogql(args.query, self._team)
        except HogQLValidationError as e:
            raise MaxToolRetryableError(f"Query validation failed: {e}")

        result = await execute_hogql_query(
            team=self._team,
            query=validated_query,
            name="",
            description="",
        )

        return result, {"query": args.query}
