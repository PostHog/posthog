import asyncio
from collections import defaultdict
from typing import TypedDict

import yaml
from posthoganalytics import capture_exception

from posthog.api.search import EntityConfig, class_queryset
from posthog.models import Action, Cohort, Dashboard, Experiment, FeatureFlag, Insight, Survey, Team, User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.sync import database_sync_to_async

from ee.hogai.utils.types.base import EntityType

from .prompts import ENTITY_TYPE_SUMMARY_TEMPLATE, FOUND_ENTITIES_MESSAGE_TEMPLATE, HYPERLINK_USAGE_INSTRUCTIONS

ENTITY_MAP: dict[str, EntityConfig] = {
    "insight": {
        "klass": Insight,
        "search_fields": {"name": "A", "description": "C", "query_metadata": "B"},
        "extra_fields": ["name", "description", "query", "query_metadata"],
    },
    "dashboard": {
        "klass": Dashboard,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
    },
    "experiment": {
        "klass": Experiment,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
    },
    "feature_flag": {"klass": FeatureFlag, "search_fields": {"key": "A", "name": "C"}, "extra_fields": ["key", "name"]},
    "action": {
        "klass": Action,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
    },
    "cohort": {
        "klass": Cohort,
        "search_fields": {"name": "A", "description": "C", "filters": "B"},
        "extra_fields": ["name", "description", "filters"],
    },
    "survey": {
        "klass": Survey,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
    },
}
"""
Map of entity names to their class, search_fields and extra_fields.

The value in search_fields corresponds to the PostgreSQL weighting i.e. A, B, C or D.
"""


class EntitySearchTaskResult(TypedDict):
    entity_type: str | EntityType
    results: list[dict]
    warning: str | None


class EntitySearchToolkit:
    MAX_ENTITY_RESULTS = 10
    MAX_CONCURRENT_SEARCHES = 10

    def __init__(self, team: Team, user: User):
        self._team = team
        self._user = user

    @property
    def user_access_control(self) -> UserAccessControl:
        return UserAccessControl(user=self._user, team=self._team, organization_id=self._team.organization.id)

    def build_url(self, entity_type: str | EntityType, result_id: str) -> str:
        base_url = f"/project/{self._team.id}"
        match entity_type:
            case EntityType.INSIGHT:
                return f"{base_url}/insights/{result_id}"
            case EntityType.DASHBOARD:
                return f"{base_url}/dashboard/{result_id}"
            case EntityType.EXPERIMENT:
                return f"{base_url}/experiments/{result_id}"
            case EntityType.FEATURE_FLAG:
                return f"{base_url}/feature_flags/{result_id}"
            case EntityType.NOTEBOOK:
                return f"{base_url}/notebooks/{result_id}"
            case EntityType.ACTION:
                return f"{base_url}/data-management/actions/{result_id}"
            case EntityType.COHORT:
                return f"{base_url}/cohorts/{result_id}"
            case EntityType.SURVEY:
                return f"{base_url}/surveys/{result_id}"
            case _:
                return f"{base_url}/{entity_type}/{result_id}"

    def _get_formatted_entity_result(self, result: dict) -> str:
        entity_type = result["type"]
        result_id = result["result_id"]
        extra_fields = result.get("extra_fields", {})

        result_dict = {
            "name": extra_fields.get("name", f"{entity_type.upper()} {result_id}"),
            "extra_fields": extra_fields,
            "type": entity_type.title(),
            "id": result_id,
            "url": self.build_url(entity_type, result_id),
        }

        return yaml.dump(result_dict, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()

    async def _gather_bounded(self, limit: int, coros: list[object]):
        sem = asyncio.Semaphore(limit)

        async def run(coro):
            async with sem:
                return await coro

        return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)

    async def _search_single_entity(self, entity_type: str | EntityType, query: str) -> EntitySearchTaskResult:
        entity_meta = ENTITY_MAP.get(entity_type)
        if not entity_meta:
            return EntitySearchTaskResult(
                entity_type=entity_type,
                results=[],
                warning=f"Invalid entity type: {entity_type}. Will not search for this entity type.",
            )

        klass_qs, _ = await database_sync_to_async(class_queryset)(
            view=self,
            klass=entity_meta["klass"],
            project_id=self._team.project_id,
            query=query,
            search_fields=entity_meta["search_fields"],
            extra_fields=entity_meta["extra_fields"],
        )

        def evaluate_queryset(klass_qs=klass_qs):
            return list(klass_qs[: self.MAX_ENTITY_RESULTS])

        entity_results = await database_sync_to_async(evaluate_queryset)()

        return EntitySearchTaskResult(entity_type=entity_type, results=entity_results, warning=None)

    def _format_results_for_display(
        self, query: str, entity_types: list[str | EntityType], results: list[dict], counts: dict[str, int]
    ) -> str:
        content = ""
        if not results:
            content += f"No entities found matching the query '{query}' for entity types {entity_types}"
        else:
            result_summary = []
            for result in results:
                result_summary.append(self._get_formatted_entity_result(result))

            total_results = len(results)
            content += FOUND_ENTITIES_MESSAGE_TEMPLATE.format(
                total_results=total_results, entities_list="\n---\n".join(result_summary)
            )

            if counts:
                content += ENTITY_TYPE_SUMMARY_TEMPLATE.format(
                    entity_type_summary="\n".join(
                        [f"- {entity_type.title()}: {count}" for entity_type, count in counts.items() if count > 0]
                    )
                )
            content += f"\n\n{HYPERLINK_USAGE_INSTRUCTIONS}"
        return content

    async def search_entities(self, query: str, entity_types: list[str | EntityType]) -> str:
        """Search for entities by query and optional entity types."""
        try:
            if not query:
                return "No search query was provided"

            entity_types = entity_types if len(entity_types) > 0 else list(ENTITY_MAP.keys())
            tasks = [self._search_single_entity(entity_type, query) for entity_type in entity_types]
            task_results = await self._gather_bounded(self.MAX_CONCURRENT_SEARCHES, tasks)

            results: list[dict] = []
            counts: dict[str, int] = defaultdict(int)
            content = ""
            for task_result in task_results:
                if isinstance(task_result, Exception):
                    content += f"Error searching: {str(task_result)}\n"
                    continue

                entity_type = task_result["entity_type"]
                if task_result.get("warning"):
                    content += f"Error searching {entity_type}: {task_result['warning']}\n"
                    continue

                results.extend(task_result["results"])
                counts[entity_type] = len(task_result["results"])

            if results and "rank" in results[0]:
                results.sort(key=lambda x: x.get("rank", 0), reverse=True)

            # Format all results for display
            content += self._format_results_for_display(query, entity_types, results, counts)

            return content

        except Exception as e:
            capture_exception(e, distinct_id=self._user.distinct_id)

            return f"Error searching entities: {str(e)}"
