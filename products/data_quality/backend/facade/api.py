"""
Facade for data_quality.

The only module this product's presentation layer (and external code) may import. It carries
capability functions and frozen contracts, and nothing else: the check registry, the type specs and
the AST-bearing ``CheckPlan`` stay inside ``logic``, since they are compiler internals rather than
data. ORM model classes never cross here either -- ``facade/models.py`` is their one channel.
"""

from ..activity_logging import log_metric_schedule_change
from ..logic.checks import (
    checks_for_subject,
    edit_check,
    empty_check_suite,
    ensure_name_available,
    live_subject_checks,
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
from ..logic.permissions import authorized_subject_types, restrict_subject_types, writable_subjects
from ..logic.registry import UnknownCheckTypeError, list_check_types
from ..logic.run_records import record_check_run
from ..logic.schedules import MetricCheckSchedule, ScheduleUnavailableError, get_schedule, set_schedule
from ..logic.serialization import compute_fingerprint, from_config_entry, to_config_entry
from ..logic.subject_access import (
    DenialContext,
    ReadableSubjects,
    ReferencedSubjects,
    caller_denial_context,
    can_be_object_denied,
    definition_reads_unreadable_subject,
    denial_context,
    memoized_definition_verdict,
    readable_check_subjects,
    suites_backing_unreadable_runs_q,
    unreadable_suites_q,
    visible_check_queryset,
    visible_checks,
    without_denied_runs,
)
from ..logic.subjects import resolve_metric_subjects, resolve_subject
from ..logic.triggers import materialization_audit_mode as quality_audit_mode
from .contracts import CheckTypeInfo

__all__ = [
    "log_metric_schedule_change",
    "MetricCheckSchedule",
    "ScheduleUnavailableError",
    "CheckConfigError",
    "CheckEditConflict",
    "CheckStatusRow",
    "CheckTypeInfo",
    "CompiledCheck",
    "DenialContext",
    "ReadableSubjects",
    "ReferencedSubjects",
    "SubjectKey",
    "SubjectIdentity",
    "SubjectLocation",
    "SubjectRef",
    "SubjectUnresolvableError",
    "UnknownCheckTypeError",
    "authorized_subject_types",
    "restrict_subject_types",
    "live_subject_checks",
    "caller_denial_context",
    "can_be_object_denied",
    "checks_for_subject",
    "compile_check",
    "compute_fingerprint",
    "definition_reads_unreadable_subject",
    "memoized_definition_verdict",
    "denial_context",
    "readable_check_subjects",
    "edit_check",
    "empty_check_suite",
    "ensure_name_available",
    "from_config_entry",
    "get_gate_config",
    "get_schedule",
    "list_check_types",
    "notify_materialization_blocked",
    "quality_audit_mode",
    "record_check_run",
    "related_subject_ref",
    "resolve_subject",
    "resolve_metric_subjects",
    "roll_up_health",
    "set_gate_materialization_on_checks",
    "set_schedule",
    "soft_delete_check",
    "start_check_suite",
    "subject_health",
    "subject_locations",
    "suites_backing_unreadable_runs_q",
    "to_config_entry",
    "unreadable_suites_q",
    "upsert_check",
    "validate_check",
    "visible_checks",
    "visible_check_queryset",
    "without_denied_runs",
    "writable_subjects",
]
