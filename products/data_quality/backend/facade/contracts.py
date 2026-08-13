"""
Contract types for data_quality.

Frozen, framework-free values other products need. No Django imports.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, TypeGuard

CHECK_SUITE_WORKFLOW_NAME = "data-quality-run-suite"

MATERIALIZATION_GATE_ACTIVITY_NAME = "data-quality-materialization-gate"

# How a materialization should treat this subject's checks, resolved by ``quality_audit_mode``.
# skip: no runnable checks (or the product flag is off) -- zero overhead, the old path.
# warn: run checks after publish, fire-and-forget.
# gate: audit staged data before the publish pointer flip; blocking failures stop the publish.
QualityAuditMode = Literal["skip", "warn", "gate"]

QUALITY_AUDIT_SKIP: QualityAuditMode = "skip"
QUALITY_AUDIT_WARN: QualityAuditMode = "warn"
QUALITY_AUDIT_GATE: QualityAuditMode = "gate"


def is_quality_audit_mode(value: str) -> TypeGuard[QualityAuditMode]:
    """Whether a value crossing the Temporal boundary is a mode this code knows.

    A workflow reads the mode off a recorded activity result, so a history written by another
    deploy can carry a value this version never defined. The caller decides what to do with a
    stranger; nothing here may assume the string is one of ours.
    """
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
