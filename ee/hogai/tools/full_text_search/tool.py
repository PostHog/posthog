from enum import StrEnum

from django.conf import settings

import yaml
from posthoganalytics import capture_exception

from posthog.api.search import EntityConfig, search_entities
from posthog.models import Action, Cohort, Dashboard, Experiment, FeatureFlag, Insight, Survey
from posthog.rbac.user_access_control import UserAccessControl
from posthog.sync import database_sync_to_async

from ee.hogai.core.shared_prompts import HYPERLINK_USAGE_INSTRUCTIONS
from ee.hogai.tool import MaxSubtool

from .prompts import ENTITY_TYPE_SUMMARY_TEMPLATE, FOUND_ENTITIES_MESSAGE_TEMPLATE

EXCLUDE_FROM_DISPLAY: dict[str, set[str]] = {
    "insight": {"query"},
}
"""Fields to exclude from display output per entity type (they're still used for search ranking)."""

ENTITY_MAP: dict[str, EntityConfig] = {
    "insight": {
        "klass": Insight,
        "search_fields": {"name": "A", "description": "C", "query_metadata": "B"},
        "extra_fields": ["name", "description", "query_metadata", "query"],
        "filters": {"deleted": False, "saved": True},
    },
    "dashboard": {
        "klass": Dashboard,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
        "filters": {"deleted": False},
    },
    "experiment": {
        "klass": Experiment,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
        "filters": {"deleted": False},
    },
    "feature_flag": {
        "klass": FeatureFlag,
        "search_fields": {"key": "A", "name": "C"},
        "extra_fields": ["key", "name"],
        "filters": {"deleted": False},
    },
    "action": {
        "klass": Action,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
        "filters": {"deleted": False},
    },
    "cohort": {
        "klass": Cohort,
        "search_fields": {"name": "A", "description": "C", "filters": "B"},
        "extra_fields": ["name", "description", "filters"],
        "filters": {"deleted": False},
    },
    "survey": {
        "klass": Survey,
        "search_fields": {"name": "A", "description": "C"},
        "extra_fields": ["name", "description"],
        "filters": {"archived": False},
    },
}
"""
Map of entity names to their class, search_fields and extra_fields.

The value in search_fields corresponds to the PostgreSQL weighting i.e. A, B, C or D.
"""


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
    MAX_ENTITY_RESULTS = 10
    MAX_CONCURRENT_SEARCHES = 10

    async def execute(self, query: str, search_kind: FTSKind) -> str:
        """Search for entities by query and entity."""
        try:
            if not query:
                return "No search query was provided"

            if search_kind == FTSKind.ALL:
                entity_types = set(ENTITY_MAP.keys())
            elif search_kind in SEARCH_KIND_TO_DATABASE_ENTITY_TYPE:
                entity_types = {SEARCH_KIND_TO_DATABASE_ENTITY_TYPE[search_kind]}
            else:
                return f"Invalid entity kind: {search_kind}. Will not perform search for it."

            results, counts = await database_sync_to_async(search_entities, thread_sensitive=False)(
                entity_types,
                query,
                self._team.project_id,
                self,  # type: ignore
                ENTITY_MAP,
            )

            content = self._format_results_for_display(query, entity_types, results, counts)
            return content

        except Exception as e:
            capture_exception(e, distinct_id=self._user.distinct_id)

            return f"Error searching entities: {str(e)}"

    @property
    def user_access_control(self) -> UserAccessControl:
        return UserAccessControl(user=self._user, team=self._team, organization_id=self._team.organization.id)

    def _build_url(self, entity_type: str, result_id: str) -> str:
        base_url = f"{settings.SITE_URL}/project/{self._team.id}"
        match entity_type:
            case "insight":
                return f"{base_url}/insights/{result_id}"
            case "dashboard":
                return f"{base_url}/dashboard/{result_id}"
            case "experiment":
                return f"{base_url}/experiments/{result_id}"
            case "feature_flag":
                return f"{base_url}/feature_flags/{result_id}"
            case "notebook":
                return f"{base_url}/notebooks/{result_id}"
            case "action":
                return f"{base_url}/data-management/actions/{result_id}"
            case "cohort":
                return f"{base_url}/cohorts/{result_id}"
            case "survey":
                return f"{base_url}/surveys/{result_id}"
            case _:
                raise ValueError(f"Unknown entity type: {entity_type}")

    def _omit_none_values(self, obj):
        """Recursively remove None values from dicts and sequences."""
        if isinstance(obj, dict):
            return {k: self._omit_none_values(v) for k, v in obj.items() if v is not None}
        elif isinstance(obj, list | tuple):
            return type(obj)(self._omit_none_values(item) for item in obj if item is not None)
        else:
            return obj

    def _get_formatted_entity_result(self, result: dict) -> str:
        entity_type = result["type"]
        result_id = result["result_id"]
        extra_fields = result.get("extra_fields", {})

        # Filter out fields that shouldn't be displayed
        exclude_fields = EXCLUDE_FROM_DISPLAY.get(entity_type, set())
        display_extra_fields = {k: v for k, v in extra_fields.items() if k not in exclude_fields}

        result_dict = {
            "name": extra_fields.get("name", f"{entity_type.upper()} {result_id}"),
            "type": entity_type.title(),
            f"{entity_type}_id": result_id,
            "url": self._build_url(entity_type, result_id),
            "extra_fields": display_extra_fields,
        }

        cleaned_dict = self._omit_none_values(result_dict)
        return yaml.dump(cleaned_dict, default_flow_style=False, allow_unicode=True, sort_keys=False, indent=1).strip()

    def _format_results_for_display(
        self, query: str, entity_types: set[str], results: list[dict], counts: dict[str, int | None]
    ) -> str:
        content = ""
        if not results:
            content += f"No entities found matching the query '{query}' for entity types {list(entity_types)}"
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
