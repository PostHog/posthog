from typing import Any, Optional, Union
from dataclasses import dataclass
from enum import Enum


class OrganizationSettingKey(str, Enum):
    """
    Predefined setting keys for organization settings.
    Only adding new settings is currently supported.
    """

    USER_CAN_SHARE_PUBLICLY = "user_can_share_publicly"


class OrganizationSettingAccessLevel(str, Enum):
    """Access levels that can be affected by settings"""

    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"


class SettingType(str, Enum):
    """Setting value types"""

    BOOLEAN = "boolean"
    STRING = "string"
    INTEGER = "integer"
    JSON = "json"
    CHOICE = "choice"


@dataclass
class ValidationRule:
    """Validation rule for a setting"""

    rule_type: str  # 'regex', 'range', 'custom'
    rule: Any  # The actual rule (pattern, range dict, etc.)
    message: str


@dataclass
class OrganizationSettingDefinition:
    """Definition for an organization setting"""

    key: OrganizationSettingKey
    name: str
    description: str
    default_value: Any
    validation_rules: Optional[dict[str, Any]] = None
    feature_flag: Optional[str] = None
    access_levels_affected_up_to: Optional[OrganizationSettingAccessLevel] = None

    def __post_init__(self):
        """Validate the definition after initialization"""
        if not isinstance(self.key, OrganizationSettingKey):
            raise ValueError(f"key must be an OrganizationSettingKey enum value, got {type(self.key)}")

        if self.validation_rules and not isinstance(self.validation_rules, dict):
            raise ValueError("validation_rules must be a dictionary")

        if self.feature_flag and not isinstance(self.feature_flag, str):
            raise ValueError("feature_flag must be a string")

        if self.access_levels_affected_up_to and not isinstance(
            self.access_levels_affected_up_to, OrganizationSettingAccessLevel
        ):
            raise ValueError("access_levels_affected_up_to must be an OrganizationSettingAccessLevel enum value")


# Define all organization setting definitions
ORGANIZATION_SETTING_DEFINITIONS: dict[OrganizationSettingKey, OrganizationSettingDefinition] = {
    OrganizationSettingKey.USER_CAN_SHARE_PUBLICLY: OrganizationSettingDefinition(
        key=OrganizationSettingKey.USER_CAN_SHARE_PUBLICLY,
        name="User Can Share Publicly",
        description="Allow users to share dashboards and insights publicly",
        default_value=True,
        validation_rules={"type": "boolean"},
        feature_flag="organization-settings-sharing",
        access_levels_affected_up_to=OrganizationSettingAccessLevel.MEMBER,
    ),
}


def get_setting_definition(setting_key: Union[str, OrganizationSettingKey]) -> Optional[OrganizationSettingDefinition]:
    """Get a specific setting definition by key"""
    if isinstance(setting_key, str):
        try:
            setting_key = OrganizationSettingKey(setting_key)
        except ValueError:
            return None

    definitions = ORGANIZATION_SETTING_DEFINITIONS.values()
    for definition in definitions:
        if definition.key == setting_key:
            return definition

    return None


def get_all_definitions() -> list[OrganizationSettingDefinition]:
    """Get all organization setting definitions"""
    return list(ORGANIZATION_SETTING_DEFINITIONS.values())


def get_definitions_for_user(user, organization) -> list[OrganizationSettingDefinition]:
    """Get setting definitions that are available for a specific user"""
    from posthog.services.organization_settings import OrganizationSettingsService

    service = OrganizationSettingsService(organization)
    all_definitions = get_all_definitions()
    available_definitions = []

    for definition in all_definitions:
        if service.is_setting_available_for_user(definition, user):
            available_definitions.append(definition)

    return available_definitions


def get_definitions_by_features(feature_keys: list[str]) -> list[OrganizationSettingDefinition]:
    """Get definitions that require any of the specified features"""
    definitions = []

    for definition in ORGANIZATION_SETTING_DEFINITIONS.values():
        if definition.is_deprecated:
            continue

        if definition.enabled_when_features_available:
            for feature_key in definition.enabled_when_features_available:
                if feature_key in feature_keys:
                    definitions.append(definition)
                    break

    return definitions


def is_user_affected_by_setting(setting_key: str, user, organization) -> bool:
    """Check if a user is affected by a specific setting (i.e., if the setting applies to their access level)"""
    definition = get_setting_definition(setting_key)
    if not definition:
        return False

    # If no access levels are specified as affected, assume it affects everyone
    if definition.access_levels_affected_up_to is None:
        return True

    try:
        membership = organization.memberships.get(user=user)
        user_level = membership.level
    except:
        return False

    # Check if user's level is at or below the affected level
    return user_level <= definition.access_levels_affected_up_to
