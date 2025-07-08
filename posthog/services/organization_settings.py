from typing import Any, Union
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_settings import OrganizationSetting
from posthog.models.organization_setting_definitions import (
    OrganizationSettingKey,
    get_setting_definition,
    get_definitions_by_features,
)


class OrganizationSettingsService:
    """Service for managing organization settings"""

    def __init__(self, organization: Organization):
        self.organization = organization
        self.settings_manager = OrganizationSetting.objects

    def get_setting(self, setting_key: Union[str, OrganizationSettingKey]) -> Any:
        """Get a setting value"""
        if isinstance(setting_key, OrganizationSettingKey):
            setting_key = setting_key.value
        return self.settings_manager.get_setting(self.organization, setting_key)

    def set_setting(
        self, setting_key: Union[str, OrganizationSettingKey], value: Any, user=None
    ) -> OrganizationSetting:
        """Set a setting value with validation"""
        if isinstance(setting_key, OrganizationSettingKey):
            setting_key = setting_key.value
        return self.settings_manager.set_setting(self.organization, setting_key, value, user)

    def get_all_settings(self) -> dict[str, Any]:
        """Get all settings for the organization"""
        return self.settings_manager.get_settings_for_organization(self.organization)

    def is_setting_active(self, setting_key: Union[str, OrganizationSettingKey]) -> bool:
        """Check if a setting is active for this organization (considering feature availability)"""
        if isinstance(setting_key, OrganizationSettingKey):
            setting_key = setting_key.value

        definition = get_setting_definition(setting_key)
        if not definition:
            return False

        if definition.enabled_when_features_available:
            for feature_key in definition.enabled_when_features_available:
                if not self.organization.is_feature_available(feature_key):
                    return False
        return True

    def can_user_edit_setting(self, setting_key: Union[str, OrganizationSettingKey], user) -> bool:
        """Check if a user can edit a specific setting"""
        if isinstance(setting_key, OrganizationSettingKey):
            setting_key = setting_key.value

        definition = get_setting_definition(setting_key)
        if not definition:
            return False

        try:
            membership = OrganizationMembership.objects.get(user=user, organization=self.organization)

            # Check access level
            if membership.level < definition.minimum_access_level:
                return False

            # Check feature availability
            if definition.enabled_when_features_available:
                for feature_key in definition.enabled_when_features_available:
                    if not self.organization.is_feature_available(feature_key):
                        return False

            return True
        except OrganizationMembership.DoesNotExist:
            return False

    def get_settings_by_features(self, feature_keys: list[str]) -> list[dict[str, Any]]:
        """Get all settings that require any of the specified features"""
        definitions = get_definitions_by_features(feature_keys)
        settings = []

        for definition in definitions:
            value = self.get_setting(definition.setting_key)
            settings.append({"key": definition.setting_key.value, "value": value, "definition": definition})

        return settings

    def get_all_settings_with_definitions(self) -> dict[str, Any]:
        """Get all settings for the organization with their definitions"""
        return self.settings_manager.get_settings_for_organization(self.organization)

    def can_user_perform_action(self, setting_key: Union[str, OrganizationSettingKey], user) -> bool:
        """Check if a user can perform an action based on a setting (considers if setting is active and user is affected)"""
        if isinstance(setting_key, OrganizationSettingKey):
            setting_key = setting_key.value

        # First check if the setting is active
        if not self.is_setting_active(setting_key):
            return True  # If setting is not active, no restrictions apply

        # Check if user is affected by this setting
        from posthog.models.organization_setting_definitions import is_user_affected_by_setting

        if not is_user_affected_by_setting(setting_key, user, self.organization):
            return True  # If user is not affected, no restrictions apply

        # Get the setting value
        setting_value = self.get_setting(setting_key)

        # For boolean settings, return the setting value directly
        definition = get_setting_definition(setting_key)
        if definition and definition.setting_type.value == "boolean":
            return setting_value

        # For other types, you might want different logic
        # For now, return True if setting has any value (not None/False)
        return bool(setting_value)
