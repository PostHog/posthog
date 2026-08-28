"""
Facade for data_quality.

The only module this product's presentation layer (and external code) may import. It carries
capability functions and frozen contracts, and nothing else: the check registry, the type specs and
the AST-bearing ``CheckPlan`` stay inside ``logic``, since they are compiler internals rather than
data. ORM model classes never cross here either -- ``facade/models.py`` is their one channel.
"""

from ..logic.checks import (
    checks_for_subject,
    edit_check,
    empty_check_suite,
    ensure_name_available,
    soft_delete_check,
    start_check_suite,
    subject_health,
    upsert_check,
    validate_check,
)
from ..logic.compiler import compile_check, related_subject_ref
from ..logic.config import get_gate_config, set_gate_materialization_on_checks
from ..logic.contracts import CompiledCheck, SubjectRef
from ..logic.errors import CheckConfigError, CheckEditConflict, SubjectUnresolvableError
from ..logic.health import CheckStatusRow, roll_up_health
from ..logic.navigation import SubjectKey, SubjectLocation, subject_locations
from ..logic.notifications import notify_materialization_blocked
from ..logic.registry import UnknownCheckTypeError, list_check_types
from ..logic.run_records import record_check_run
from ..logic.serialization import compute_fingerprint, from_config_entry, to_config_entry
from ..logic.subject_access import (
    DenialContext,
    ReadableSubjects,
    ReferencedSubjects,
    caller_denial_context,
    can_be_object_denied,
    check_type_reads_beyond_subject,
    definition_reads_unreadable_subject,
    denial_context,
    denied_subject_names,
    hidden_check_ids,
    is_subject_denied,
    referenced_subject_names,
    referenced_subjects,
    referencing_check_types,
    suites_backing_unreadable_runs_q,
    unreadable_runs_q,
    unreadable_suites_q,
)
from ..logic.subjects import resolve_subject
from ..logic.triggers import materialization_audit_mode as quality_audit_mode
from .contracts import CheckTypeInfo

__all__ = [
    "CheckConfigError",
    "CheckEditConflict",
    "CheckStatusRow",
    "CheckTypeInfo",
    "CompiledCheck",
    "DenialContext",
    "ReadableSubjects",
    "ReferencedSubjects",
    "SubjectKey",
    "SubjectLocation",
    "SubjectRef",
    "SubjectUnresolvableError",
    "UnknownCheckTypeError",
    "caller_denial_context",
    "can_be_object_denied",
    "check_type_reads_beyond_subject",
    "checks_for_subject",
    "compile_check",
    "compute_fingerprint",
    "definition_reads_unreadable_subject",
    "denial_context",
    "denied_subject_names",
    "edit_check",
    "empty_check_suite",
    "ensure_name_available",
    "from_config_entry",
    "get_gate_config",
    "hidden_check_ids",
    "is_subject_denied",
    "list_check_types",
    "notify_materialization_blocked",
    "quality_audit_mode",
    "record_check_run",
    "referenced_subject_names",
    "referenced_subjects",
    "referencing_check_types",
    "related_subject_ref",
    "resolve_subject",
    "roll_up_health",
    "set_gate_materialization_on_checks",
    "soft_delete_check",
    "start_check_suite",
    "subject_health",
    "subject_locations",
    "suites_backing_unreadable_runs_q",
    "to_config_entry",
    "unreadable_runs_q",
    "unreadable_suites_q",
    "upsert_check",
    "validate_check",
]
