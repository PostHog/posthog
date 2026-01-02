from typing import Any, Literal

from django.conf import settings

import yaml
from pydantic import ValidationError

from posthog.schema import DocumentArtifactContent, VisualizationArtifactContent

from posthog.api.search import EntityConfig, search_entities
from posthog.models import Action, Cohort, Dashboard, Experiment, FeatureFlag, Insight, Survey, Team, User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.sync import database_sync_to_async

from ee.hogai.context.context import AssistantContextManager

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

EXCLUDE_FROM_DISPLAY: dict[str, set[str]] = {
    "insight": {"query", "query_metadata"},
}
"""Fields to exclude from display output per entity type (they're still used for search ranking)."""


class EntitySearchContext:
    """Context manager for searching/listing and formatting Django models."""

    def __init__(self, team: Team, user: User, context_manager: AssistantContextManager):
        self._team = team
        self._user = user
        self._context_manager = context_manager

    @property
    def user_access_control(self) -> UserAccessControl:
        # The `search_entities` function uses this field for access control.
        return UserAccessControl(user=self._user, team=self._team, organization_id=self._team.organization.id)

    async def search_entities(
        self,
        entity_types: set[str] | Literal["all"],
        query: str,
    ) -> tuple[list[dict], dict[str, int | None]]:
        """
        Search for entities by query and entity types.

        Args:
            entity_types: Set of entity type strings to search or "all" to search all entities
            query: Search query string

        Returns:
            Tuple of (results list, counts dict)
        """
        if entity_types == "all":
            entity_types = set(ENTITY_MAP.keys())

        results, counts, _ = await database_sync_to_async(search_entities, thread_sensitive=False)(
            entity_types,
            query,
            self._team.project_id,
            self,  # type: ignore
            ENTITY_MAP,
        )
        return results, counts

    async def list_entities(
        self,
        entity_type: str,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        List entities with pagination support, sorted by updated_at DESC.

        Args:
            entity_type: Type of entity to list (insight, dashboard, artifact, etc.)
            limit: Number of entities to return
            offset: Number of entities to skip

        Returns:
            Tuple of (entities list, total count)
        """
        all_entities: list[dict[str, Any]] = []

        # Fetch artifacts if requested
        if entity_type == "artifact":
            artifacts, total_count = await self._context_manager.artifacts.aget_conversation_artifacts(limit, offset)

            # Convert artifacts to the same format as database entities
            for artifact in artifacts:
                try:
                    content = artifact.content
                    match content:
                        case VisualizationArtifactContent():
                            extra_fields = {
                                "name": content.name,
                                "description": content.description,
                            }
                        case DocumentArtifactContent():
                            extra_fields = {}
                    all_entities.append(
                        {
                            "type": "artifact",
                            "result_id": artifact.short_id,
                            "extra_fields": extra_fields,
                        }
                    )
                except ValidationError:
                    # Skip artifacts that can't be parsed
                    continue
        else:
            # Fetch database entities
            db_results, _, total_count = await database_sync_to_async(search_entities, thread_sensitive=False)(
                entities={entity_type},
                query=None,  # No search query, just listing
                project_id=self._team.project_id,
                view=self,  # type: ignore
                entity_map=ENTITY_MAP,
                limit=limit,
                offset=offset,
            )
            all_entities.extend(db_results)

        return all_entities, total_count

    def format_entities_as_yaml(self, entities: list[dict]) -> list[str]:
        """
        Format a list of entities as YAML strings.

        Args:
            entities: List of entity result dicts

        Returns:
            List of YAML formatted strings
        """
        formatted_entities = []
        for entity in entities:
            formatted_entities.append(self._get_formatted_entity_result(entity))
        return formatted_entities

    def _get_formatted_entity_result(self, result: dict) -> str:
        """
        Format an entity result as YAML.

        Args:
            result: Entity result dict with 'type', 'result_id', and 'extra_fields'

        Returns:
            YAML formatted string representing the entity
        """
        entity_type = result["type"]
        result_id = result["result_id"]
        extra_fields = result.get("extra_fields", {})

        # Filter out fields that shouldn't be displayed
        exclude_fields = EXCLUDE_FROM_DISPLAY.get(entity_type, set())
        display_extra_fields = {k: v for k, v in extra_fields.items() if k not in exclude_fields}

        result_dict = {
            "name": extra_fields.get("name", f"{entity_type.upper()} {result_id}"),
            "type": entity_type.title().replace("_", " "),
            f"{entity_type}_id": result_id,
        }

        # Add URL if not an artifact
        try:
            result_dict["url"] = self._build_url(entity_type, result_id, self._team.id)
        except ValueError:
            pass

        # Add extra_fields if there are any fields beyond name
        fields_to_include = {k: v for k, v in display_extra_fields.items() if k != "name"}
        if fields_to_include:
            result_dict["extra_fields"] = fields_to_include

        cleaned_dict = self._omit_none_values(result_dict)
        return yaml.dump(cleaned_dict, default_flow_style=False, allow_unicode=True, sort_keys=False, indent=1).strip()

    def _build_url(self, entity_type: str, result_id: str, team_id: int) -> str:
        """Build a URL for an entity based on its type and ID."""
        base_url = f"{settings.SITE_URL}/project/{team_id}"
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
            case "error_tracking_issue":
                return f"{base_url}/error_tracking/{result_id}"
            case _:
                raise ValueError(f"Unknown entity type: {entity_type}")

    def _omit_none_values(self, obj: Any):
        """Recursively remove None values from dicts and sequences."""
        if isinstance(obj, dict):
            if not obj:
                return None
            return {k: self._omit_none_values(v) for k, v in obj.items() if v is not None}
        elif isinstance(obj, list | tuple):
            return type(obj)(self._omit_none_values(item) for item in obj if item is not None)
        else:
            return obj
