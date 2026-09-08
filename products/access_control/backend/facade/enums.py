"""
Exported enums and constants for access_control.

Small products can keep enums in contracts.py instead. Split
into this file when contracts.py gets crowded.

Rule: if an enum appears in a contract dataclass field, it
belongs here (or in contracts.py). Shared types that other
products need to interpret contract objects also belong here.

Internal-only constants (DB magic values, feature flags, etc.)
should stay in the implementation (logic.py, models.py).
"""

from typing import Literal

from django.db import models

ResolvedAccessSourceValue = Literal[
    "object",
    "parent_object",
    "resource",
    "parent_resource",
    "system_default",
    "org_admin",
    "creator",
    "org_membership",
]
ResolvedAccessSourceSubjectValue = Literal["member", "role", "default"]


class ResolvedAccessSource(models.TextChoices):
    """The `ResolvedAccessSourceValue` literals as choices, so the schema names the enum after this class."""

    OBJECT = "object"
    PARENT_OBJECT = "parent_object"
    RESOURCE = "resource"
    PARENT_RESOURCE = "parent_resource"
    SYSTEM_DEFAULT = "system_default"
    ORG_ADMIN = "org_admin"
    CREATOR = "creator"
    ORG_MEMBERSHIP = "org_membership"


class ResolvedAccessSourceSubject(models.TextChoices):
    """The `ResolvedAccessSourceSubjectValue` literals as choices, so the schema names the enum after this class."""

    MEMBER = "member"
    ROLE = "role"
    DEFAULT = "default"
