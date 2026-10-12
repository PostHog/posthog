"""
Exported enums for authz.

If an enum appears in a contract dataclass field, it belongs here.
Internal-only constants (DB magic values, feature flags) stay in
the implementation (logic.py, models.py).

No Django imports: use LabeledStrEnum or LabeledIntEnum, not
models.TextChoices, for an enum that backs model or serializer choices.
"""

from posthog.enums import LabeledStrEnum


class SplineStatus(LabeledStrEnum):
    PENDING = "pending"
    RETICULATED = "reticulated"
