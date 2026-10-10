from typing import Literal

from pydantic import BaseModel, Field

from ee.hogai.context.entity_search.context import EntitySearchContext
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.tools.list_data import LIST_RESULT_PROMPT
from ee.hogai.utils.prompt import format_prompt_string

LIST_FEATURE_FLAGS_TOOL_PROMPT = """
Use this tool to list feature flags with their status, optionally filtered by status or by key/name, with pagination.

To find a specific flag by its key or name, use `search` with the key or name exactly as the user wrote it.
Do not add words such as "flag" or "feature flag", and do not page through all flags to find one flag.

Prefer this over listing all flags and reading them one by one — results already include each
flag's status, so you never need to inspect flags individually to find stale ones.

# Parameters:
- status: Optional status filter:
    - "stale": enabled flags safe to remove (not evaluated in 30+ days, or never evaluated but 100% rolled out and 30+ days old)
    - "enabled": currently enabled flags
    - "disabled": currently disabled flags
    - omit to list all flags
- search: Optional text. Returns only flags whose key or name contains this text (case-insensitive). An exact key match comes first.
- limit: Results per page (1-100, default 100)
- offset: Number to skip for pagination (default 0)

# Examples:
- "Show me all stale feature flags" → status="stale"
- "Which flags are disabled?" → status="disabled"
- "List my feature flags" → no status
- "Is enterprise-agent-builder-ux-refresh enabled?" → search="enterprise-agent-builder-ux-refresh"
- "Show the checkout flags" → search="checkout"
""".strip()

# Maps the user-facing status filter to the backend `active` query param values.
_STATUS_TO_ACTIVE_FILTER: dict[str, str] = {"stale": "STALE", "enabled": "true", "disabled": "false"}


class ListFeatureFlagsToolArgs(BaseModel):
    status: Literal["stale", "enabled", "disabled"] | None = Field(
        default=None, description="Filter flags by status. Omit to list all flags."
    )
    search: str | None = Field(
        default=None,
        description="Only return flags whose key or name contains this text. Pass a flag key exactly as written.",
    )
    limit: int = Field(default=100, ge=1, le=100, description="Number of feature flags to return per page")
    offset: int = Field(default=0, ge=0, description="Number of feature flags to skip for pagination")


class ListFeatureFlagsTool(MaxTool):
    name: Literal["list_feature_flags"] = "list_feature_flags"
    description: str = LIST_FEATURE_FLAGS_TOOL_PROMPT
    context_prompt_template: str = (
        "Lists feature flags with their status, filterable by stale/enabled/disabled and by key or name"
    )
    args_schema: type[BaseModel] = ListFeatureFlagsToolArgs

    def get_required_resource_access(self):
        return [("feature_flag", "viewer")]

    async def _arun_impl(
        self, *, status: str | None = None, search: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[str, ToolMessagesArtifact | None]:
        active_filter = _STATUS_TO_ACTIVE_FILTER[status] if status else None

        entities_context = EntitySearchContext(team=self._team, user=self._user, context_manager=self._context_manager)
        all_entities, total_count = await entities_context.list_feature_flags(
            limit, offset, active_filter=active_filter, search=search
        )

        formatted_entities = entities_context.format_entities(all_entities)

        has_more = total_count > offset + limit
        next_offset = offset + limit if has_more else None

        return format_prompt_string(
            LIST_RESULT_PROMPT,
            results=formatted_entities,
            offset=offset,
            limit=limit,
            next_offset=next_offset,
        ), None
