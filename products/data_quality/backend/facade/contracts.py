"""
Contract types for data_quality.

Frozen, framework-free values other products need. No Django imports.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, TypeGuard

from posthog.dataclasses import frozen

from .enums import SuiteRunTrigger

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


@frozen
class RunCheckSuiteInputs:
    """What to run. Exactly one selector is expected; a suite with no matching checks is not an error.

    ``node_ids`` is the materialization path: the DAG workflow knows nodes, not saved queries, and
    the mapping is resolved inside the prepare activity so the workflow stays deterministic.
    ``table_ids`` is the source-sync path, keyed on the table so it works with or without a DAG.
    """

    team_id: int
    trigger: SuiteRunTrigger
    saved_query_ids: list[str] = field(default_factory=list)
    table_ids: list[str] = field(default_factory=list)
    metric_ids: list[str] = field(default_factory=list)
    check_ids: list[str] = field(default_factory=list)
    node_ids: list[str] = field(default_factory=list)
    suite_run_id: str | None = None
    schedule_id: str | None = None
    data_modeling_job_id: str | None = None
    created_by_id: int | None = None
    # Audits the staged folder rather than the published table. Needs exactly one saved query.
    staged_queryable_folder: str | None = None
