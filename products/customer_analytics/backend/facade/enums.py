from posthog.enums import LabeledStrEnum


class AccountPropertyPinKind(LabeledStrEnum):
    CUSTOM_PROPERTY = "custom_property", "Custom property"
    RELATIONSHIP = "relationship", "Relationship"


# Mirrors OPTION_COLOR_TOKENS in the frontend's customPropertyTypes.ts (DataColorToken presets).
# The labels repeat the values because the published OpenAPI enum lists these exact pairs.
class CustomPropertyOptionColor(LabeledStrEnum):
    PRESET_1 = "preset-1", "preset-1"
    PRESET_2 = "preset-2", "preset-2"
    PRESET_3 = "preset-3", "preset-3"
    PRESET_4 = "preset-4", "preset-4"
    PRESET_5 = "preset-5", "preset-5"
    PRESET_6 = "preset-6", "preset-6"
    PRESET_7 = "preset-7", "preset-7"
    PRESET_8 = "preset-8", "preset-8"
    PRESET_9 = "preset-9", "preset-9"
    PRESET_10 = "preset-10", "preset-10"


class AccountViewVisibility(LabeledStrEnum):
    PRIVATE = "private", "Personal"
    TEAM = "team", "Team"


class TaskDigestCadence(LabeledStrEnum):
    """How often a user's customer task digest email is sent."""

    WEEKDAYS = "weekdays", "Weekdays"
    EVERY_DAY = "every_day", "Every day"


class AccountRelationshipSource(LabeledStrEnum):
    """Which kind of writer created or ended a relationship row. Rows written before provenance
    was recorded carry NULL."""

    HUMAN = "human", "Human"
    WORKFLOW = "workflow", "Workflow"
    AI = "ai", "AI"
    SALESFORCE_CLAIM = "salesforce_claim", "Salesforce claim"
    MIGRATION = "migration", "Migration"


class OwnershipRoleState(LabeledStrEnum):
    """What a consumer may conclude about a controlled relationship on one account."""

    # No control row: legacy authority holds, whatever the relationship rows say.
    UNMANAGED = "unmanaged", "Unmanaged"
    ASSIGNED = "assigned", "Assigned"
    # Managed with no active holder: an explicit decision that the role is empty.
    CLEARED = "cleared", "Cleared"
    # Managed, but the holder cannot be projected; consumers keep their last applied value.
    BLOCKED = "blocked", "Blocked"


class OwnershipRoleDiagnostic(LabeledStrEnum):
    HOLDER_MISSING = "holder_missing", "The active relationship has no user"
    HOLDER_INACTIVE = "holder_inactive", "The holder's user account is deactivated"
    HOLDER_NOT_IN_ORGANIZATION = "holder_not_in_organization", "The holder is not a member of the organization"
    MULTIPLE_ACTIVE_HOLDERS = "multiple_active_holders", "More than one active relationship holds the role"


__all__ = [
    "AccountPropertyPinKind",
    "AccountViewVisibility",
    "CustomPropertyOptionColor",
    "AccountRelationshipSource",
    "OwnershipRoleDiagnostic",
    "OwnershipRoleState",
    "TaskDigestCadence",
]
