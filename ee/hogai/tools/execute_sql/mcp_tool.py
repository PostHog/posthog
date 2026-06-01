from pydantic import BaseModel, Field

from posthog.schema import HogQLNotice

from posthog.hogql.metadata import get_table_names
from posthog.hogql.parser import parse_select
from posthog.hogql.taxonomy_validation import validate_taxonomy_references

from posthog.sync import database_sync_to_async

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


@mcp_tool_registry.register(scopes=["query:read"])
class ExecuteSQLMCPTool(HogQLOutputParserMixin, MCPTool[ExecuteSQLMCPToolArgs]):
    """
    MCP version of ExecuteSQLTool.

    Executes HogQL queries without LangChain context or artifact creation.
    """

    name = "execute_sql"
    args_schema = ExecuteSQLMCPToolArgs

    async def execute(self, args: ExecuteSQLMCPToolArgs) -> str:
        try:
            validated_query = await self._validate_hogql_query(args.query)
        except PydanticOutputParserException as e:
            raise MaxToolRetryableError(f"Query validation failed: {e.validation_message}")

        # Warn (non-fatally) when the query references events/properties absent from the project
        # taxonomy — the most common silent-wrong-answer surface for agents (e.g. `event = 'purchase'`
        # returning 0 because the real event is `paid_bill`). The query still runs.
        taxonomy_warnings = await self._get_taxonomy_warnings(validated_query.query)

        insight_context = InsightContext(
            team=self._team,
            query=validated_query,
            name="",
            description="",
            user=self._user,
        )
        results = await insight_context.execute_and_format(
            prompt_template="{{{results}}}", truncate_results=args.truncate
        )

        return _prepend_taxonomy_warnings(results, taxonomy_warnings)

    @database_sync_to_async(thread_sensitive=False)
    def _get_taxonomy_warnings(self, query: str) -> list[HogQLNotice]:
        # Reuses the already-validated query's AST parse — no ClickHouse round-trip. Any parse failure
        # is already surfaced by _validate_hogql_query, so swallow it here rather than double-report.
        try:
            parsed_query = parse_select(query, placeholders={})
        except Exception:
            return []
        table_names = get_table_names(parsed_query)
        return validate_taxonomy_references(parsed_query, self._team, table_names)


def _prepend_taxonomy_warnings(results: str, warnings: list[HogQLNotice]) -> str:
    if not warnings:
        return results

    lines = "\n".join(f"- {warning.message}" for warning in warnings)
    return (
        "<taxonomy_warnings>\n"
        "Your query references names that don't exist in this project's taxonomy. "
        "If a result looks empty or unexpected, a wrong event/property name is the likely cause — "
        "check these before trusting the result:\n"
        f"{lines}\n"
        "</taxonomy_warnings>\n\n"
        f"{results}"
    )
