from enum import StrEnum
from functools import cached_property

from posthoganalytics import capture_exception

from ee.hogai.context.entity_search import EntitySearchContext
from ee.hogai.core.shared_prompts import HYPERLINK_USAGE_INSTRUCTIONS
from ee.hogai.tool import MaxSubtool

from .prompts import ENTITY_TYPE_SUMMARY_TEMPLATE, FOUND_ENTITIES_MESSAGE_TEMPLATE


class FTSKind(StrEnum):
    INSIGHTS = "insights"
    DASHBOARDS = "dashboards"
    COHORTS = "cohorts"
    ACTIONS = "actions"
    EXPERIMENTS = "experiments"
    FEATURE_FLAGS = "feature_flags"
    NOTEBOOKS = "notebooks"
    SURVEYS = "surveys"
    ALL = "all"


SEARCH_KIND_TO_DATABASE_ENTITY_TYPE: dict[FTSKind, str] = {
    FTSKind.INSIGHTS: "insight",
    FTSKind.DASHBOARDS: "dashboard",
    FTSKind.EXPERIMENTS: "experiment",
    FTSKind.FEATURE_FLAGS: "feature_flag",
    FTSKind.NOTEBOOKS: "notebook",
    FTSKind.ACTIONS: "action",
    FTSKind.COHORTS: "cohort",
    FTSKind.SURVEYS: "survey",
}


class EntitySearchTool(MaxSubtool):
    @cached_property
    def _entities_context(self) -> EntitySearchContext:
        return EntitySearchContext(team=self._team, user=self._user, context_manager=self._context_manager)

    async def execute(self, query: str, search_kind: FTSKind) -> str:
        """Search for entities by query and entity."""
        try:
            if not query:
                return "No search query was provided"

            if search_kind == FTSKind.ALL:
                entity_types = "all"
            elif search_kind in SEARCH_KIND_TO_DATABASE_ENTITY_TYPE:
                entity_types = {SEARCH_KIND_TO_DATABASE_ENTITY_TYPE[search_kind]}
            else:
                return f"Invalid entity kind: {search_kind}. Will not perform search for it."

            results, counts = await self._entities_context.search_entities(entity_types, query)

            if not results:
                return f"No entities found matching the query '{query}' for entity types."

            return self._format_results_for_display(results, counts)

        except Exception as e:
            capture_exception(e, distinct_id=self._user.distinct_id)

            return f"Error searching entities: {str(e)}"

    def _format_results_for_display(self, results: list[dict], counts: dict[str, int | None]) -> str:
        result_summary = self._entities_context.format_entities(results)

        total_results = len(results)
        content = FOUND_ENTITIES_MESSAGE_TEMPLATE.format(total_results=total_results, entities_list=result_summary)

        if counts:
            content += ENTITY_TYPE_SUMMARY_TEMPLATE.format(
                entity_type_summary="\n".join(
                    [
                        f"- {entity_type.title()}: {count}"
                        for entity_type, count in counts.items()
                        if count is not None and count > 0
                    ]
                )
            )
        content += f"\n\n{HYPERLINK_USAGE_INSTRUCTIONS}"
        return content
