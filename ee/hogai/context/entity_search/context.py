from typing import Any, Literal

from django.conf import settings

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

    def format_entities(self, entities: list[dict]) -> str:
        """
        Format a list of entities as a CSV-like pipe-separated matrix.

        Args:
            entities: List of entity result dicts

        Returns:
            Pipe-separated matrix string with header row
        """
        if not entities:
            return ""

        # Determine if we have multiple entity types
        entity_types = {e["type"] for e in entities}
        multiple_types = len(entity_types) > 1

        # Collect all extra field keys across all entities (excluding standard columns)
        standard_columns = {"name", "id", "url", "type"}
        extra_columns: set[str] = set()
        for entity in entities:
            entity_type = entity["type"]
            exclude_fields = EXCLUDE_FROM_DISPLAY.get(entity_type, set())
            extra_fields = entity.get("extra_fields", {})
            for key in extra_fields:
                if key not in standard_columns and key not in exclude_fields:
                    extra_columns.add(key)

        # Build column order: ID, Name, extra fields alphabetically, URL last
        extra_columns_sorted = sorted(extra_columns)

        # Build rows
        rows: list[str] = []

        if multiple_types:
            # Header with Entity type column
            header_cols = (
                ["Entity type", "ID", "Name"]
                + [col.replace("_", " ").title() for col in extra_columns_sorted]
                + ["URL"]
            )
            rows.append("|".join(header_cols))
        else:
            # Single type: add type header line
            single_type = next(iter(entity_types))
            rows.append(f"Entity type: {single_type.replace('_', ' ').title()}")
            # Header without Entity type column
            header_cols = ["ID", "Name"] + [col.replace("_", " ").title() for col in extra_columns_sorted] + ["URL"]
            rows.append("|".join(header_cols))

        # Data rows
        for entity in entities:
            row_values = self._get_entity_row_values(entity, extra_columns_sorted, multiple_types)
            rows.append("|".join(row_values))

        return "\n".join(rows)

    def _get_entity_row_values(self, result: dict, extra_columns: list[str], include_type: bool) -> list[str]:
        """
        Get the row values for an entity.

        Args:
            result: Entity result dict with 'type', 'result_id', and 'extra_fields'
            extra_columns: List of extra column names to include
            include_type: Whether to include the entity type as first column

        Returns:
            List of escaped string values for the row
        """
        entity_type = result["type"]
        result_id = result["result_id"]
        extra_fields = result.get("extra_fields", {})

        # Get name (from extra_fields or generate default)
        name = extra_fields.get("name", f"{entity_type.upper()} {result_id}")

        # Get URL if available
        try:
            url = self._build_url(entity_type, result_id, self._team.id)
        except ValueError:
            url = ""

        # Build row values: Entity type (if multiple), ID, Name, extra fields, URL last
        values: list[str] = []
        if include_type:
            values.append(self._escape_value(entity_type.replace("_", " ").title()))
        values.append(self._escape_value(result_id))
        values.append(self._escape_value(name))

        # Add extra field values
        exclude_fields = EXCLUDE_FROM_DISPLAY.get(entity_type, set())
        for col in extra_columns:
            if col in exclude_fields:
                values.append("-")
            else:
                val = extra_fields.get(col)
                values.append(self._escape_value(val))

        # URL goes last
        values.append(self._escape_value(url))

        return values

    def _escape_value(self, value: Any) -> str:
        """Escape a value for CSV output, quoting if it contains pipe characters."""
        if value is None or value == "":
            return "-"
        str_val = str(value)
        return f'"{str_val}"' if "|" in str_val else str_val

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
