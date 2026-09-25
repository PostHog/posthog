from enum import Enum

from django.db import models


class AccountPropertyPinKind(str, Enum):
    CUSTOM_PROPERTY = "custom_property"
    RELATIONSHIP = "relationship"


class TaskDigestCadence(models.TextChoices):
    """How often a user's customer task digest email is sent."""

    WEEKDAYS = "weekdays", "Weekdays"
    EVERY_DAY = "every_day", "Every day"


class AccountRelationshipSource(models.TextChoices):
    """Which kind of writer created or ended a relationship row. Rows written before provenance
    was recorded carry NULL."""

    HUMAN = "human", "Human"
    WORKFLOW = "workflow", "Workflow"
    AI = "ai", "AI"
    SALESFORCE_CLAIM = "salesforce_claim", "Salesforce claim"
    MIGRATION = "migration", "Migration"


class OwnershipRoleState(models.TextChoices):
    """What a consumer may conclude about a controlled relationship on one account."""

    # No control row: legacy authority holds, whatever the relationship rows say.
    UNMANAGED = "unmanaged", "Unmanaged"
    ASSIGNED = "assigned", "Assigned"
    # Managed with no active holder: an explicit decision that the role is empty.
    CLEARED = "cleared", "Cleared"
    # Managed, but the holder cannot be projected; consumers keep their last applied value.
    BLOCKED = "blocked", "Blocked"


class OwnershipRoleDiagnostic(models.TextChoices):
    HOLDER_MISSING = "holder_missing", "The active relationship has no user"
    HOLDER_INACTIVE = "holder_inactive", "The holder's user account is deactivated"
    HOLDER_NOT_IN_ORGANIZATION = "holder_not_in_organization", "The holder is not a member of the organization"
    MULTIPLE_ACTIVE_HOLDERS = "multiple_active_holders", "More than one active relationship holds the role"


__all__ = [
    "AccountPropertyPinKind",
    "AccountRelationshipSource",
    "OwnershipRoleDiagnostic",
    "OwnershipRoleState",
    "TaskDigestCadence",
]
