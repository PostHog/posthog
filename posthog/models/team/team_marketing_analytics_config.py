import logging

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.schema import NodeKind, SourceMap

from posthog.models.team import Team

# Based on team_revenue_analytics_config.py

logger = logging.getLogger(__name__)


def validate_sources_map(sources_map: dict) -> None:
    """Validate sources_map structure: dict of source_id -> dict of string mappings."""
    if not isinstance(sources_map, dict):
        raise ValidationError("sources_map must be a dictionary")

    for source_id, field_mapping in sources_map.items():
        if not isinstance(source_id, str):
            raise ValidationError(f"Source ID '{source_id}' must be a string")

        if not isinstance(field_mapping, dict):
            raise ValidationError(f"Field mapping for source '{source_id}' must be a dictionary")

        # Validate that field mappings are strings or None
        for schema_field, mapped_field in field_mapping.items():
            if not isinstance(schema_field, str):
                raise ValidationError(f"Schema field key '{schema_field}' in source '{source_id}' must be a string")

            if mapped_field is not None and not isinstance(mapped_field, str):
                raise ValidationError(
                    f"Source '{source_id}' field mapping for '{schema_field}' must be a string or None, got {type(mapped_field)}"
                )


def validate_conversion_goals(conversion_goals: list) -> None:
    """Validate conversion goals structure: list of dicts with name, event, and properties."""
    if not isinstance(conversion_goals, list):
        raise ValidationError("conversion_goals must be a list")
    for goal in conversion_goals:
        if not isinstance(goal, dict):
            raise ValidationError(f"Conversion goal must be a dictionary, got {type(goal)}")
        if not isinstance(goal.get("name"), str):
            raise ValidationError(f"Conversion goal name must be a string, got {type(goal.get('name'))}")
        if goal.get("id") and not isinstance(goal.get("id"), str) and not isinstance(goal.get("id"), int):
            raise ValidationError(f"Conversion goal id must be a string or integer, got {type(goal.get('id'))}")
        if not isinstance(goal.get("schema_map"), dict):
            raise ValidationError(
                f"Conversion goal schema_map must be a dictionary, got {type(goal.get('schema_map'))}"
            )
        if goal.get("kind") is None:
            raise ValidationError("Conversion goal must have a 'kind' field")
        if goal.get("kind") == NodeKind.EVENTS_NODE:
            if goal.get("id") and not isinstance(goal.get("id"), str):
                raise ValidationError(f"Conversion goal id must be a string, got {type(goal.get('id'))}")
        elif goal.get("kind") == NodeKind.ACTIONS_NODE:
            # we should try to convert the id to an integer
            try:
                goal["id"] = int(goal["id"])
            except ValueError:
                raise ValidationError(
                    f"Conversion goal id must be convertible to an integer, got {type(goal.get('id'))}"
                )
        elif goal.get("kind") == NodeKind.DATA_WAREHOUSE_NODE:
            # Validate all required fields for ConversionGoalFilter3 schema
            if not isinstance(goal.get("id"), str):
                raise ValidationError(f"Conversion goal id must be a string, got {type(goal.get('id'))}")

            # Ensure id_field is present and is a string
            if goal.get("id_field") is None:
                raise ValidationError("DataWarehouseNode conversion goal must have an 'id_field' field")
            if not isinstance(goal.get("id_field"), str):
                raise ValidationError(f"Conversion goal id_field must be a string, got {type(goal.get('id_field'))}")

            # Ensure distinct_id_field is present and is a string
            if goal.get("distinct_id_field") is None:
                raise ValidationError("DataWarehouseNode conversion goal must have a 'distinct_id_field' field")
            if not isinstance(goal.get("distinct_id_field"), str):
                raise ValidationError(
                    f"Conversion goal distinct_id_field must be a string, got {type(goal.get('distinct_id_field'))}"
                )

            # Ensure table_name is present and is a string
            if goal.get("table_name") is None:
                raise ValidationError("DataWarehouseNode conversion goal must have a 'table_name' field")
            if not isinstance(goal.get("table_name"), str):
                raise ValidationError(
                    f"Conversion goal table_name must be a string, got {type(goal.get('table_name'))}"
                )

            # Ensure timestamp_field is present and is a string
            if goal.get("timestamp_field") is None:
                raise ValidationError("DataWarehouseNode conversion goal must have a 'timestamp_field' field")
            if not isinstance(goal.get("timestamp_field"), str):
                raise ValidationError(
                    f"Conversion goal timestamp_field must be a string, got {type(goal.get('timestamp_field'))}"
                )
        else:
            raise ValidationError(
                f"Conversion goal kind must be one of {NodeKind.EVENTS_NODE}, {NodeKind.ACTIONS_NODE} or {NodeKind.DATA_WAREHOUSE_NODE}, got {goal.get('kind')}"
            )


# Intentionally not inheriting from UUIDModel because we're using a OneToOneField
# and therefore using the exact same primary key as the Team model.
class TeamMarketingAnalyticsConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    # Mangled fields incoming:
    # Because we want to validate the schema for these fields, we'll have mangled DB fields/columns
    # that are then wrapped by schema-validation getters/setters
    _sources_map = models.JSONField(default=dict, db_column="sources_map", null=False, blank=True)
    _conversion_goals = models.JSONField(default=list, db_column="conversion_goals", null=True, blank=True)

    @property
    def sources_map(self) -> dict[str, dict]:
        return self._sources_map or {}

    @sources_map.setter
    def sources_map(self, value: dict) -> None:
        value = value or {}
        try:
            validate_sources_map(value)
            self._sources_map = value
        except ValidationError as e:
            raise ValidationError(f"Invalid sources map schema: {str(e)}")

    @property
    def sources_map_typed(self) -> dict[str, SourceMap]:
        """Return sources_map as typed SourceMap objects for Python usage"""
        response = {}
        for source_id, field_mapping in self._sources_map.items():
            if field_mapping is None:
                response[source_id] = SourceMap()
            else:
                response[source_id] = SourceMap(**field_mapping)
        return response

    def update_source_mapping(self, source_id: str, field_mapping: dict) -> None:
        """Update or add a single source mapping while preserving existing sources."""

        # Get current sources_map
        current_sources = self.sources_map.copy()

        # Update the specific source
        current_sources[source_id] = field_mapping

        # Validate and set the updated sources_map
        self.sources_map = current_sources

    def update_source_field_mapping(self, source_id: str, field_mappings: dict) -> None:
        """Update specific field mappings for a source while preserving other fields."""

        # Get current sources_map
        current_sources = self.sources_map.copy()

        # Ensure the source exists
        if source_id not in current_sources:
            current_sources[source_id] = {}

        # Update only the specified field mappings
        current_sources[source_id].update(field_mappings)

        # Validate and set the updated sources_map
        self.sources_map = current_sources

    def remove_source_mapping(self, source_id: str) -> None:
        """Remove a source mapping entirely."""

        current_sources = self.sources_map.copy()
        if source_id in current_sources:
            del current_sources[source_id]
            self.sources_map = current_sources

    @property
    def conversion_goals(self) -> list:
        return self._conversion_goals or []

    @conversion_goals.setter
    def conversion_goals(self, value: list) -> None:
        value = value or []
        try:
            validate_conversion_goals(value)
            self._conversion_goals = value
        except ValidationError as e:
            raise ValidationError(f"Invalid conversion goals: {str(e)}")

    def to_cache_key_dict(self) -> dict:
        return {
            "base_currency": self.team.base_currency,
            "sources_map": self.sources_map,
        }


# This is best effort, we always attempt to create the config manually
# when accessing it via `Team.marketing_analytics_config`.
# In theory, this shouldn't ever fail, but it does fail in some tests cases
# so let's make it very forgiving
@receiver(post_save, sender=Team)
def create_team_marketing_analytics_config(sender, instance, created, **kwargs):
    try:
        if created:
            TeamMarketingAnalyticsConfig.objects.get_or_create(team=instance)
    except Exception as e:
        logger.warning(f"Error creating team marketing analytics config: {e}")
