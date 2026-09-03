"""
Contract types for data_quality.

Frozen, framework-free values other products need. No Django imports.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, TypeGuard

CHECK_SUITE_WORKFLOW_NAME = "data-quality-run-suite"

MATERIALIZATION_GATE_ACTIVITY_NAME = "data-quality-materialization-gate"

QualityAuditMode = Literal["skip", "warn", "gate"]

QUALITY_AUDIT_SKIP: QualityAuditMode = "skip"
QUALITY_AUDIT_WARN: QualityAuditMode = "warn"
QUALITY_AUDIT_GATE: QualityAuditMode = "gate"


def is_quality_audit_mode(value: str) -> TypeGuard[QualityAuditMode]:
    """A recorded Temporal history can carry a mode another deploy defined and this one does not."""
    return value in (QUALITY_AUDIT_SKIP, QUALITY_AUDIT_WARN, QUALITY_AUDIT_GATE)


@dataclass(frozen=True)
class CheckTypeInfo:
    """One entry of the check-type catalog, so a caller can author config without guessing.

    Carries what the registry knows about a type, flattened to plain values -- the spec object
    itself stays internal, since it is a compiler, not data.
    """

    check_type: str
    description: str
    requires_column: bool
    config_schema: dict[str, Any] = field(default_factory=dict)
