from pydantic import BaseModel, Field

from posthog.schema import AssistantHogQLQuery, HogQLQuery

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.chat_agent.sql.mixins import HogQLOutputParserMixin
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.mcp_tool import MCPTool, mcp_tool_registry
from ee.hogai.tool_errors import MaxToolRetryableError


class ExecuteSQLMCPToolArgs(BaseModel):
    query: str = Field(description="The final SQL query to be executed.")
    truncate: bool = Field(
        default=True,
        description="Whether to truncate large blob/JSON values in results. Set to false for full untruncated results.",
    )
    connectionId: str | None = Field(
        default=None,
        description=(
            "Optional id of an external data source (e.g. a Postgres or DuckDB direct-query connection). "
            "When set, runs the query against that source instead of the ClickHouse catalog. "
            "Use external-data-sources-list to discover available connection ids."
        ),
    )


@mcp_tool_registry.register(scopes=["query:read"])
class ExecuteSQLMCPTool(HogQLOutputParserMixin, MCPTool[ExecuteSQLMCPToolArgs]):
    """
    MCP version of ExecuteSQLTool.

    Executes HogQL queries without LangChain context or artifact creation.
    """

    name = "execute_sql"
    args_schema = ExecuteSQLMCPToolArgs

    async def execute(self, args: ExecuteSQLMCPToolArgs) -> str:
        query: AssistantHogQLQuery | HogQLQuery
        if args.connectionId:
            # Queries targeting an external connection reference tables that aren't in the
            # default ClickHouse database, so the local parse/print HogQL validation step
            # would reject them. Defer validation to the runner, which resolves the schema
            # for the selected connection.
            cleaned_query = args.query.rstrip(";").strip() if args.query else ""
            if not cleaned_query:
                raise MaxToolRetryableError("Query validation failed: Query is empty")
            query = HogQLQuery(query=cleaned_query, connectionId=args.connectionId)
        else:
            try:
                query = await self._validate_hogql_query(args.query)
            except PydanticOutputParserException as e:
                raise MaxToolRetryableError(f"Query validation failed: {e.validation_message}")

        insight_context = InsightContext(
            team=self._team,
            query=query,
            name="",
            description="",
            user=self._user,
        )
        return await insight_context.execute_and_format(prompt_template="{{{results}}}", truncate_results=args.truncate)
