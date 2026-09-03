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

from django.db import models


class ResolvedAccessSource(models.TextChoices):
    """How a resolved access level was derived. Mirrors `ResolvedAccess.source`."""

    OBJECT = "object", "object"
    PARENT_OBJECT = "parent_object", "parent_object"
    RESOURCE = "resource", "resource"
    PARENT_RESOURCE = "parent_resource", "parent_resource"
    SYSTEM_DEFAULT = "system_default", "system_default"
    ORG_ADMIN = "org_admin", "org_admin"
    CREATOR = "creator", "creator"
    ORG_MEMBERSHIP = "org_membership", "org_membership"


class ResolvedAccessSourceSubject(models.TextChoices):
    """Whose rule decided a resolved access level. Mirrors `ResolvedAccess.source_subject`."""

    MEMBER = "member", "member"
    ROLE = "role", "role"
    DEFAULT = "default", "default"
