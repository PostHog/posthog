from typing import TypedDict

import yaml
from posthoganalytics import capture_exception

from posthog.api.search import EntityConfig, search_entities
from posthog.models import Action, Cohort, Dashboard, Experiment, FeatureFlag, Insight, Survey, Team, User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.sync import database_sync_to_async

from ee.hogai.graph.shared_prompts import HYPERLINK_USAGE_INSTRUCTIONS
from ee.hogai.utils.types.base import EntityType

from .prompts import ENTITY_TYPE_SUMMARY_TEMPLATE, FOUND_ENTITIES_MESSAGE_TEMPLATE

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

    def _format_results_for_display(
        self, query: str, entity_types: set[str] | set[EntityType], results: list[dict], counts: dict[str, int | None]
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
                        [
                            f"- {entity_type.title()}: {count}"
                            for entity_type, count in counts.items()
                            if count is not None and count > 0
                        ]
                    )
                )
            content += f"\n\n{HYPERLINK_USAGE_INSTRUCTIONS}"
        return content

    async def search(self, query: str, entity_types: list[str] | list[EntityType]) -> str:
        """Search for entities by query and optional entity types."""
        try:
            if not query:
                return "No search query was provided"

            entities = set(entity_types) if len(entity_types) > 0 else set(ENTITY_MAP.keys())
            valid_entity_types = set()
            content = ""
            for entity_type in entities:
                entity_meta = ENTITY_MAP.get(entity_type)
                if not entity_meta:
                    content += f"Invalid entity type: {entity_type}. Will not search for this entity type."
                else:
                    valid_entity_types.add(entity_type)

            if len(valid_entity_types) == 0:
                return "No valid entity types were provided. Will not search for any entity types."

            results, counts = await database_sync_to_async(search_entities)(
                valid_entity_types, query, self._team.project_id, self, ENTITY_MAP
            )  # type: ignore

            # Format all results for display
            content += self._format_results_for_display(query, valid_entity_types, results, counts)
            return content

        except Exception as e:
            capture_exception(e, distinct_id=self._user.distinct_id)

            return f"Error searching entities: {str(e)}"
