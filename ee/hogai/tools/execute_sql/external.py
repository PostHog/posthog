from pydantic import BaseModel, Field

from posthog.models import Team, User

from ee.hogai.external_tool import ExternalTool, ExternalToolResult, register_external_tool
from ee.hogai.tool_errors import MaxToolRetryableError

from .core import HogQLValidationError, execute_hogql_query, validate_hogql


class ExecuteSQLExternalToolArgs(BaseModel):
    query: str = Field(description="The final SQL query to be executed.")


@register_external_tool
class ExecuteSQLExternalTool(ExternalTool):
    """
    External version of ExecuteSQLTool for API/MCP callers.

    Executes HogQL queries without LangChain context or artifact creation.
    """

    name = "execute_sql"
    args_schema = ExecuteSQLExternalToolArgs

    async def execute(self, team: Team, user: User, **args) -> ExternalToolResult:
        query_str = args.get("query", "")

        # Validate the HogQL query
        try:
            validated_query = await validate_hogql(query_str, team)
        except HogQLValidationError as e:
            return ExternalToolResult(
                success=False,
                content=f"Query validation failed: {e}",
                error="validation_error",
            )

        # Execute the query
        try:
            result = await execute_hogql_query(
                team=team,
                query=validated_query,
                name="",
                description="",
            )
        except MaxToolRetryableError as e:
            return ExternalToolResult(
                success=False,
                content=f"Query execution failed: {e}",
                error="execution_error",
            )
        except Exception as e:
            return ExternalToolResult(
                success=False,
                content=f"Unexpected error: {e}",
                error="unexpected_error",
            )

        return ExternalToolResult(
            success=True,
            content=result,
            data={"query": query_str},
        )
