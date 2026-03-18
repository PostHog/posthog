from typing import Literal

from pydantic import BaseModel, Field

from ee.hogai.context.entity_search.context import SEARCH_KIND_TO_DATABASE_ENTITY_TYPE, EntityKind, EntitySearchContext
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.utils.prompt import format_prompt_string

LIST_DATA_TOOL_PROMPT = """
Use this tool to browse/search PostHog entities with pagination, sorted by name.

# Use this when:
- The user wants to browse their saved work
- You need to find entities but don't have the ID
- The user asks "what insights do I have?" or similar
- After searching, to discover additional relevant entities that search may have missed due to different naming

# Parameters:
- kind: Type to list (e.g., "insights", "dashboards")
- limit: Results per page (1-100, default 100)
- offset: Number to skip for pagination (default 0)

# Pagination workflow:
1. First call: offset=0, limit=100 (gets first 100)
2. If has_more indicated, next call: offset=100, limit=100 (gets next 100)
3. Continue incrementing offset by limit

# Examples:
- "Show me my recent insights" → kind="insights"
- "List all dashboards" → kind="dashboards"
""".strip()

ENTITIES = [f"{entity}" for entity in EntityKind if entity not in (EntityKind.ALL)]

ListEntityKind = Literal["artifacts", *ENTITIES]  # type: ignore

LIST_RESULT_PROMPT = """
Offset {{{offset}}}, limit {{{limit}}}.

# Results
{{{results}}}

---
{{#next_offset}}
<system_reminder>To see more results, use offset={{{next_offset}}}</system_reminder>
{{/next_offset}}
{{^next_offset}}
<system_reminder>You reached the end of results for this entity type.</system_reminder>
{{/next_offset}}
""".strip()


class ListDataToolArgs(BaseModel):
    kind: ListEntityKind = Field(description="Select the entity type you want to list")
    limit: int = Field(default=100, ge=1, le=100, description="Number of entities to return per page")
    offset: int = Field(default=0, ge=0, description="Number of entities to skip for pagination")


class ListDataTool(MaxTool):
    name: Literal["list_data"] = "list_data"
    description: str = LIST_DATA_TOOL_PROMPT
    context_prompt_template: str = "Lists PostHog entities with pagination"
    args_schema: type[BaseModel] = ListDataToolArgs

    async def _arun_impl(
        self, *, kind: str, limit: int = 100, offset: int = 0
    ) -> tuple[str, ToolMessagesArtifact | None]:
        if kind == "artifacts":
            normalized_kind = "artifact"
        else:
            normalized_kind = SEARCH_KIND_TO_DATABASE_ENTITY_TYPE[EntityKind(kind)]

        entities_context = EntitySearchContext(team=self._team, user=self._user, context_manager=self._context_manager)
        all_entities, total_count = await entities_context.list_entities(normalized_kind, limit, offset)

        formatted_entities = entities_context.format_entities(all_entities)

        # Build pagination metadata
        has_more = total_count > offset + limit
        next_offset = offset + limit if has_more else None

        return format_prompt_string(
            LIST_RESULT_PROMPT,
            results=formatted_entities,
            offset=offset,
            limit=limit,
            next_offset=next_offset,
        ), None
