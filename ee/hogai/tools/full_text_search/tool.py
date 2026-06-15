from functools import cached_property
from typing import Literal

from ee.hogai.context.entity_search import EntitySearchContext
from ee.hogai.context.entity_search.context import SEARCH_KIND_TO_DATABASE_ENTITY_TYPE, EntityKind
from ee.hogai.core.shared_prompts import HYPERLINK_USAGE_INSTRUCTIONS
from ee.hogai.tool import MaxSubtool
from ee.hogai.utils.prompt import format_prompt_string

from .prompts import (
    ENTITY_TYPE_SUMMARY_PROMPT,
    FOUND_ENTITIES_PROMPT,
    INVALID_ENTITY_KIND_PROMPT,
    NO_ENTITIES_FOUND_PROMPT,
    NO_SEARCH_QUERY_PROVIDED_PROMPT,
)


class EntitySearchTool(MaxSubtool):
    @cached_property
    def _entities_context(self) -> EntitySearchContext:
        return EntitySearchContext(team=self._team, user=self._user, context_manager=self._context_manager)

    async def execute(self, query: str, search_kind: EntityKind) -> str:
        """Search for entities by query and entity."""
        if not query:
            return NO_SEARCH_QUERY_PROVIDED_PROMPT

        entity_types: set[str] | Literal["all"]
        if search_kind == EntityKind.ALL:
            entity_types = "all"
        elif search_kind in SEARCH_KIND_TO_DATABASE_ENTITY_TYPE:
            entity_types = {SEARCH_KIND_TO_DATABASE_ENTITY_TYPE[search_kind]}
        else:
            return format_prompt_string(INVALID_ENTITY_KIND_PROMPT, kind=search_kind)

        results, counts = await self._entities_context.search_entities(entity_types, query)

        if not results:
            return format_prompt_string(NO_ENTITIES_FOUND_PROMPT, query=query)

        return self._format_results_for_display(results, counts)

    def _format_results_for_display(self, results: list[dict], counts: dict[str, int | None]) -> str:
        result_summary = self._entities_context.format_entities(results)

        total_results = len(results)
        content = format_prompt_string(FOUND_ENTITIES_PROMPT, total_results=total_results, entities_list=result_summary)

        if counts:
            content += format_prompt_string(
                ENTITY_TYPE_SUMMARY_PROMPT,
                entity_type_summary="\n".join(
                    [
                        f"- {entity_type.title()}: {count}"
                        for entity_type, count in counts.items()
                        if count is not None and count > 0
                    ]
                ),
            )
        content += f"\n\n{HYPERLINK_USAGE_INSTRUCTIONS}"
        return content
