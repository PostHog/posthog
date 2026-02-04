from typing import Any

from posthog.sync import database_sync_to_async

from ee.hogai.chat_agent.query_planner.toolkit import TaxonomyAgentToolkit
from ee.hogai.external_tool import ExternalTool, register_external_tool
from ee.hogai.tool_errors import MaxToolRetryableError

from .core import ReadTaxonomyToolArgs, execute_taxonomy_query


@register_external_tool(scopes=["insight:read", "query:read"])
class ReadTaxonomyExternalTool(ExternalTool[ReadTaxonomyToolArgs]):
    """
    External version of ReadTaxonomyTool for API/MCP callers.

    Explores the user's taxonomy (events, actions, properties, and property values).
    """

    name = "read_taxonomy"
    args_schema = ReadTaxonomyToolArgs

    async def execute(self, args: ReadTaxonomyToolArgs) -> tuple[str, dict[str, Any] | None]:
        toolkit = TaxonomyAgentToolkit(self._team)

        try:

            @database_sync_to_async(thread_sensitive=False)
            def _execute_query():
                return execute_taxonomy_query(args.query, toolkit, self._team)

            res = await _execute_query()
        except ValueError as e:
            raise MaxToolRetryableError(str(e))

        return res, {"query": args.query.model_dump()}
