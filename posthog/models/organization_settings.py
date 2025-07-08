from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.postgres.fields import JSONField
from posthog.models.utils import UUIDModel, sane_repr
from posthog.models.organization_setting_definitions import get_setting_definition, get_all_definitions


class OrganizationSetting(UUIDModel):
    """Stores actual setting values for organizations"""

    organization = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE, related_name="settings")
    setting_key = models.CharField(max_length=100)
    setting_value = JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_organization_settings"
    )
    updated_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="updated_organization_settings"
    )

    class Meta:
        db_table = "posthog_organization_settings"
        unique_together = ["organization", "setting_key"]
        indexes = [
            models.Index(fields=["organization", "setting_key"]),
            models.Index(fields=["setting_key"]),
        ]

    def __str__(self):
        return f"{self.organization.name}: {self.setting_key}"

    __repr__ = sane_repr("organization", "setting_key")

    def clean(self):
        """Validate setting value against definition"""
        definition = get_setting_definition(self.setting_key)
        if not definition:
            raise ValidationError(f"No definition found for setting key: {self.setting_key}")

        self._validate_setting_value(definition)

    def _validate_setting_value(self, definition):
        """Validate setting value against its definition"""
        # Type validation
        if definition.setting_type.value == "boolean":
            if not isinstance(self.setting_value, bool):
                raise ValidationError(f"Setting {self.setting_key} must be a boolean value")
        elif definition.setting_type.value == "string":
            if not isinstance(self.setting_value, str):
                raise ValidationError(f"Setting {self.setting_key} must be a string value")
        elif definition.setting_type.value == "integer":
            if not isinstance(self.setting_value, int):
                raise ValidationError(f"Setting {self.setting_key} must be an integer value")
        elif definition.setting_type.value == "choice":
            if self.setting_value not in (definition.choices or []):
                raise ValidationError(f"Setting {self.setting_key} must be one of: {definition.choices}")

        # Custom validation rules
        if definition.validation_rules:
            for rule in definition.validation_rules:
                self._apply_validation_rule(rule, definition)

    def _apply_validation_rule(self, rule, definition):
        """Apply a specific validation rule"""
        rule_type = rule.rule_type
        rule_value = rule.rule
        error_message = rule.message

        if rule_type == "regex":
            import re

            if not re.match(rule_value, str(self.setting_value)):
                raise ValidationError(error_message)
        elif rule_type == "range":
            min_val = rule_value.get("min")
            max_val = rule_value.get("max")
            if min_val is not None and self.setting_value < min_val:
                raise ValidationError(error_message)
            if max_val is not None and self.setting_value > max_val:
                raise ValidationError(error_message)
        elif rule_type == "custom":
            # Custom validation logic could be implemented here
            pass


class OrganizationSettingManager(models.Manager):
    """Manager for OrganizationSetting with enhanced functionality"""

    def get_setting(self, organization, setting_key):
        """Get a setting value with fallback to definition default"""
        try:
            setting = self.get(organization=organization, setting_key=setting_key)
            return setting.setting_value
        except OrganizationSetting.DoesNotExist:
            # Get default from definition
            definition = get_setting_definition(setting_key)
            if definition:
                return definition.default_value
            return None

    def set_setting(self, organization, setting_key, value, user=None):
        """Set a setting value with validation"""
        definition = get_setting_definition(setting_key)
        if not definition:
            raise ValueError(f"No definition found for setting key: {setting_key}")

        # Validate feature availability
        if definition.enabled_when_features_available:
            for feature_key in definition.enabled_when_features_available:
                if not organization.is_feature_available(feature_key):
                    raise ValueError(f"Feature {feature_key} not available for this organization")

        setting, created = self.get_or_create(
            organization=organization, setting_key=setting_key, defaults={"setting_value": value, "created_by": user}
        )

        if not created:
            setting.setting_value = value
            setting.updated_by = user
            setting.save()

        return setting

    def get_settings_for_organization(self, organization):
        """Get all settings for an organization with their definitions"""
        definitions = get_all_definitions()

        result = {}
        for definition in definitions:
            setting_value = self.get_setting(organization, definition.key.value)
            result[definition.key.value] = {"value": setting_value, "definition": definition}

        return result


# Set the custom manager
OrganizationSetting.add_to_class("objects", OrganizationSettingManager())
