from pydantic import BaseModel, Field

from posthog.schema import CostPlanStep, HogLanguage, HogQLMetadata, HogQLMetadataResponse

from posthog.hogql.metadata import get_hogql_metadata

from posthog.sync import database_sync_to_async

from ee.hogai.mcp_tool import MCPTool, MCPToolResult, mcp_tool_registry
from ee.hogai.tool_errors import MaxToolRetryableError


class ExplainSQLMCPToolArgs(BaseModel):
    query: str = Field(description="The SQL query to estimate before running it.")
    connectionId: str | None = Field(
        default=None,
        description=(
            "Optional id of a data warehouse connection. When set, the query is estimated against that "
            "source's tables instead of the ClickHouse catalog, the same as execute_sql with a connectionId."
        ),
    )


@mcp_tool_registry.register(scopes=["query:read"])
class ExplainSQLMCPTool(MCPTool[ExplainSQLMCPToolArgs]):
    """Estimate how much a query reads, per table, without running it.

    The plan is the one the SQL editor shows above the results: each scan with its size and precision,
    the filters that apply to it, and the join. An agent reads it to narrow a query before it runs.
    """

    name = "explain_sql"
    args_schema = ExplainSQLMCPToolArgs

    async def execute(self, args: ExplainSQLMCPToolArgs) -> MCPToolResult:
        query = args.query.rstrip(";").strip()
        if not query:
            raise MaxToolRetryableError("Query is empty")
        response = await self._metadata(query, args.connectionId)
        if not response.isValid:
            errors = "; ".join(error.message for error in response.errors) or "unknown error"
            raise MaxToolRetryableError(f"Query is not valid: {errors}")
        return MCPToolResult(
            content=_format_plan(response),
            structured_content={
                "scan_estimate": response.scan_estimate.model_dump(mode="json", exclude_none=True)
                if response.scan_estimate
                else None,
                "cost_plan": [step.model_dump(mode="json", exclude_none=True) for step in response.cost_plan or []],
            },
        )

    @database_sync_to_async(thread_sensitive=False)
    def _metadata(self, query: str, connection_id: str | None) -> HogQLMetadataResponse:
        return get_hogql_metadata(
            HogQLMetadata(
                kind="HogQLMetadata",
                language=HogLanguage.HOG_QL,
                query=query,
                connectionId=connection_id,
                indexUsage=True,
            ),
            self._team,
            self._user,
        )


def _format_plan(response: HogQLMetadataResponse) -> str:
    estimate = response.scan_estimate
    if estimate is None or not response.cost_plan:
        return "No estimate is available for this query. It is valid and can be run."
    qualifier = "up to" if estimate.upper_bound else "about"
    not_estimated = [table.name for table in estimate.tables if table.rows is None]
    if not_estimated:
        coverage = (
            f"from {len(estimate.tables) - len(not_estimated)} of {len(estimate.tables)} tables. "
            f"Not estimated: {', '.join(not_estimated)}."
        )
    else:
        coverage = f"across {len(estimate.tables)} table(s)."
    lines = [f"Reads {qualifier} {estimate.rows:,} rows {coverage}", ""]
    for step in response.cost_plan:
        lines.append(_format_step(step))
    lines.append("")
    lines.append(
        "Rows read, not rows returned. A filter with no index behind it does not lower the number. "
        "Narrow the timestamp range or the event names to read less."
    )
    return "\n".join(lines)


def _format_step(step: CostPlanStep) -> str:
    indent = "  " if step.kind == "filter" else ""
    line = f"{indent}- {step.message}"
    if step.fix:
        line += f"\n{indent}  Fix: {step.fix}"
    return line
