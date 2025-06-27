from django.db import models
from posthog.models.team import Team
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError
import logging

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
        if not isinstance(goal.get("type"), str):
            raise ValidationError(f"Conversion goal type must be a string, got {type(goal.get('type'))}")
        if not isinstance(goal.get("schema"), dict):
            raise ValidationError(f"Conversion goal schema must be a dictionary, got {type(goal.get('schema'))}")
        if goal.get("type") == "events":
            if goal.get("id") and not isinstance(goal.get("id"), str):
                raise ValidationError(f"Conversion goal id must be a string, got {type(goal.get('id'))}")
        # TODO: in the future we will allow actions to be selected as conversion goals
        # elif goal.get("type") == "actions":
        #     if goal.get("id") and not isinstance(goal.get("id"), int):
        #         raise ValidationError(f"Conversion goal id must be an integer, got {type(goal.get('id'))}")
        elif goal.get("type") == "data_warehouse":
            if not isinstance(goal.get("id"), str):
                raise ValidationError(f"Conversion goal id must be a string, got {type(goal.get('id'))}")
        else:
            # raise ValidationError(f"Conversion goal type must be one of 'event', 'action', or 'data_warehouse', got {goal.get('type')}")
            raise ValidationError(
                f"Conversion goal type must be one of 'event', or 'data_warehouse', got {goal.get('type')}"
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
    def sources_map(self) -> dict:
        return self._sources_map or {}

    @sources_map.setter
    def sources_map(self, value: dict) -> None:
        value = value or {}
        try:
            validate_sources_map(value)
            self._sources_map = value
        except ValidationError as e:
            raise ValidationError(f"Invalid sources map schema: {str(e)}")

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
            raise ValidationError(f"Invalid conversion goals schema: {str(e)}")


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
