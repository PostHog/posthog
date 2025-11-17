import logging

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.schema import AttributionMode, NodeKind, SourceMap

from posthog.models.team import Team

# ruff: noqa: DJ012  # Properties act as field accessors for mangled DB fields, so they need to come before save()

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


def validate_attribution_window_days(days: int) -> None:
    """Validate attribution window days is between 1 and 90."""
    if not isinstance(days, int):
        raise ValidationError("attribution_window_days must be an integer")
    if days < 1 or days > 90:
        raise ValidationError("attribution_window_days must be between 1 and 90")


def validate_attribution_mode(mode: str) -> None:
    """Validate attribution mode is a valid AttributionMode value."""
    if not isinstance(mode, str):
        raise ValidationError("attribution_mode must be a string")
    valid_modes = [attr_mode.value for attr_mode in AttributionMode]
    if mode not in valid_modes:
        raise ValidationError(f"attribution_mode must be one of {valid_modes}")


def validate_campaign_name_mappings(mappings: dict) -> None:
    """
    Validate campaign_name_mappings structure: dict of source_id -> dict of clean_name -> list of raw utm values.

    Structure: {
        "GoogleAds": {
            "Spring Sale 2024": ["spring_sale_2024", "spring-sale-2024"],
            "Black Friday": ["bf_2024", "blackfriday"]
        },
        "MetaAds": {...}
    }
    """
    if not isinstance(mappings, dict):
        raise ValidationError("campaign_name_mappings must be a dictionary")

    for source_id, campaign_mappings in mappings.items():
        if not isinstance(source_id, str):
            raise ValidationError(f"Source ID '{source_id}' must be a string")

        if not isinstance(campaign_mappings, dict):
            raise ValidationError(f"Campaign mappings for source '{source_id}' must be a dictionary")

        for clean_name, raw_values in campaign_mappings.items():
            if not isinstance(clean_name, str):
                raise ValidationError(f"Clean campaign name '{clean_name}' in source '{source_id}' must be a string")

            if not isinstance(raw_values, list):
                raise ValidationError(f"Raw values for campaign '{clean_name}' in source '{source_id}' must be a list")

            for raw_value in raw_values:
                if not isinstance(raw_value, str):
                    raise ValidationError(
                        f"Raw value '{raw_value}' for campaign '{clean_name}' in source '{source_id}' must be a string"
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

    # Attribution settings
    attribution_window_days = models.IntegerField(default=90, help_text="Attribution window in days (1-90)")
    attribution_mode = models.CharField(
        max_length=20,
        default=AttributionMode.LAST_TOUCH,
        choices=[(mode.value, mode.value.replace("_", " ").title()) for mode in AttributionMode],
        help_text="Attribution mode: first_touch or last_touch",
    )

    # Mangled fields incoming:
    # Because we want to validate the schema for these fields, we'll have mangled DB fields/columns
    # that are then wrapped by schema-validation getters/setters
    _sources_map = models.JSONField(default=dict, db_column="sources_map", null=False, blank=True)
    _conversion_goals = models.JSONField(default=list, db_column="conversion_goals", null=True, blank=True)
    _campaign_name_mappings = models.JSONField(
        default=dict,
        db_column="campaign_name_mappings",
        null=False,
        blank=True,
        help_text="Maps campaign names to lists of raw UTM values per data source",
    )

    def clean(self):
        """Validate model fields"""
        super().clean()
        validate_attribution_window_days(self.attribution_window_days)
        validate_attribution_mode(self.attribution_mode)

    def save(self, *args, **kwargs):
        """Override save to run validation"""
        self.clean()
        super().save(*args, **kwargs)

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

    @property
    def campaign_name_mappings(self) -> dict[str, dict[str, list[str]]]:
        return self._campaign_name_mappings or {}

    @campaign_name_mappings.setter
    def campaign_name_mappings(self, value: dict) -> None:
        value = value or {}
        try:
            validate_campaign_name_mappings(value)
            self._campaign_name_mappings = value
        except ValidationError as e:
            raise ValidationError(f"Invalid campaign name mappings: {str(e)}")

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

    def to_cache_key_dict(self) -> dict:
        return {
            "base_currency": self.team.base_currency,
            "sources_map": self.sources_map,
            "attribution_window_days": self.attribution_window_days,
            "attribution_mode": self.attribution_mode,
            "campaign_name_mappings": self.campaign_name_mappings,
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
