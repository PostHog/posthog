"""
Facade for data_quality.

The only module this product's presentation layer (and external code) may import. It carries
capability functions and frozen contracts, and nothing else: the check registry, the type specs and
the AST-bearing ``CheckPlan`` stay inside ``logic``, since they are compiler internals rather than
data. ORM model classes never cross here either -- ``facade/models.py`` is their one channel.
"""

from ..logic.checks import (
    RunRecording,
    checks_for_subject,
    edit_check,
    empty_check_suite,
    ensure_name_available,
    latest_run_recordings,
    soft_delete_check,
    start_check_suite,
    subject_health,
    upsert_check,
    validate_check,
)
from ..logic.compiler import compile_check, related_subject_ref
from ..logic.config import get_gate_config, set_gate_materialization_on_checks
from ..logic.contracts import CompiledCheck, SubjectIdentity, SubjectRef
from ..logic.errors import CheckConfigError, CheckEditConflict, SubjectUnresolvableError
from ..logic.health import CheckStatusRow, roll_up_health
from ..logic.navigation import SubjectKey, SubjectLocation, subject_locations
from ..logic.notifications import notify_materialization_blocked
from ..logic.registry import UnknownCheckTypeError, list_check_types
from ..logic.serialization import compute_fingerprint, from_config_entry, to_config_entry
from ..logic.subject_access import (
    ReferencedSubjects,
    can_be_object_denied,
    check_reads_denied_subject,
    check_type_reads_beyond_subject,
    denied_subject_names,
    is_subject_denied,
    pinned_subject_refs,
    pinned_subjects,
    referenced_subject_names,
    referenced_subjects,
    referencing_check_types,
    run_reads_unreadable_subject,
    unconfirmable_subject_names,
)
from ..logic.subjects import resolve_subject, resolve_subject_names, subject_identity
from ..logic.triggers import materialization_audit_mode as quality_audit_mode
from .contracts import CheckTypeInfo

__all__ = [
    "CheckConfigError",
    "CheckEditConflict",
    "CheckStatusRow",
    "CheckTypeInfo",
    "CompiledCheck",
    "ReferencedSubjects",
    "RunRecording",
    "SubjectIdentity",
    "SubjectKey",
    "SubjectLocation",
    "SubjectRef",
    "SubjectUnresolvableError",
    "UnknownCheckTypeError",
    "can_be_object_denied",
    "check_reads_denied_subject",
    "check_type_reads_beyond_subject",
    "checks_for_subject",
    "compile_check",
    "compute_fingerprint",
    "denied_subject_names",
    "edit_check",
    "empty_check_suite",
    "ensure_name_available",
    "from_config_entry",
    "get_gate_config",
    "is_subject_denied",
    "latest_run_recordings",
    "list_check_types",
    "notify_materialization_blocked",
    "pinned_subject_refs",
    "pinned_subjects",
    "quality_audit_mode",
    "referenced_subject_names",
    "referenced_subjects",
    "referencing_check_types",
    "related_subject_ref",
    "resolve_subject",
    "resolve_subject_names",
    "roll_up_health",
    "run_reads_unreadable_subject",
    "set_gate_materialization_on_checks",
    "soft_delete_check",
    "start_check_suite",
    "subject_health",
    "subject_identity",
    "subject_locations",
    "to_config_entry",
    "unconfirmable_subject_names",
    "upsert_check",
    "validate_check",
]
