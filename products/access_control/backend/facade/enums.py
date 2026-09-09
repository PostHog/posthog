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

from typing import Literal, get_args

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

# Serializer choices for the literals above. The schema names their enum components through
# ENUM_NAME_OVERRIDES in posthog/settings/web.py, because no Choices class carries these values.
RESOLVED_ACCESS_SOURCE_CHOICES: list[str] = list(get_args(ResolvedAccessSourceValue))
RESOLVED_ACCESS_SOURCE_SUBJECT_CHOICES: list[str] = list(get_args(ResolvedAccessSourceSubjectValue))
