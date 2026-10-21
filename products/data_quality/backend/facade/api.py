"""
Facade for data_quality.

The only module this product's presentation layer (and external code) may import. It carries
capability functions and frozen contracts, and nothing else: the check registry, the type specs and
the AST-bearing ``CheckPlan`` stay inside ``logic``, since they are compiler internals rather than
data. ORM model classes never cross here either -- ``facade/models.py`` is their one channel.
"""

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from posthog.models import Team, User

from ..activity_logging import log_schedule_change
from ..logic.checks import (
    checks_for_subject,
    edit_check,
    empty_check_suite,
    ensure_name_available,
    live_subject_checks,
    soft_delete_check,
    start_check_suite,
    subject_filter,
    subject_health,
    upsert_check,
    validate_check,
)
from ..logic.compiler import compile_check, related_subject_ref
from ..logic.config import get_gate_config, set_gate_materialization_on_checks
from ..logic.contracts import CompiledCheck, SubjectIdentity, SubjectRef
from ..logic.errors import CheckConfigError, CheckEditConflict, SubjectUnresolvableError
from ..logic.health import CheckStatusRow, roll_up_health
from ..logic.jev_preview import QuestionPreviewRunner
from ..logic.jev_progress import question_progress
from ..logic.jev_question import QuestionConfig
from ..logic.materialization import materialization_failure_summary
from ..logic.navigation import SubjectKey, SubjectLocation, subject_locations
from ..logic.notifications import notify_materialization_blocked
from ..logic.output_schema import metric_output_schema
from ..logic.permissions import authorized_subject_types, restrict_subject_types, sql_denial_context, writable_subjects
from ..logic.registry import UnknownCheckTypeError, list_check_types
from ..logic.run_records import record_check_run
from ..logic.schedule_service import (
    SubjectSchedule,
    get_schedule_with_history,
    list_schedules_with_history,
    schedule_with_history,
    update_schedule,
)
from ..logic.schedules import CheckSchedule, ScheduleUnavailableError, ScheduleUpdateResult, get_schedule, set_schedule
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
from ..logic.subject_schedules import runs_on_a_schedule
from ..logic.subjects import resolve_metric_subjects, resolve_subject, selectable_subjects, testable_metric_subjects
from ..logic.triggers import materialization_audit_mode as quality_audit_mode
from .contracts import CheckTypeInfo, MetricSubject, OutputColumn, QuestionPreview, SelectableSubject

logger = structlog.get_logger(__name__)

__all__ = [
    "question_progress",
    "preview_question",
    "log_schedule_change",
    "CheckSchedule",
    "ScheduleUnavailableError",
    "ScheduleUpdateResult",
    "SubjectSchedule",
    "CheckConfigError",
    "CheckEditConflict",
    "CheckStatusRow",
    "CheckTypeInfo",
    "CompiledCheck",
    "DenialContext",
    "MetricSubject",
    "OutputColumn",
    "SelectableSubject",
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
    "sql_denial_context",
    "live_subject_checks",
    "materialization_failure_summary",
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
    "get_schedule_with_history",
    "list_schedules_with_history",
    "list_check_types",
    "metric_output_schema",
    "notify_materialization_blocked",
    "quality_audit_mode",
    "record_check_run",
    "related_subject_ref",
    "resolve_subject",
    "resolve_metric_subjects",
    "roll_up_health",
    "set_gate_materialization_on_checks",
    "runs_on_a_schedule",
    "set_schedule",
    "schedule_with_history",
    "soft_delete_check",
    "start_check_suite",
    "subject_filter",
    "subject_health",
    "subject_locations",
    "selectable_subjects",
    "testable_metric_subjects",
    "suites_backing_unreadable_runs_q",
    "to_config_entry",
    "unreadable_suites_q",
    "update_schedule",
    "upsert_check",
    "validate_check",
    "visible_checks",
    "visible_check_queryset",
    "without_denied_runs",
    "writable_subjects",
]


def preview_question(
    *, team: "Team", user: "User", subject_type: str, subject_uuid: str, column_name: str, config: dict[str, Any]
) -> QuestionPreview:
    parsed = QuestionConfig.model_validate(
        validate_check(team, subject_type, subject_uuid, "question", column_name, config)
    )
    subject = resolve_subject(team.id, subject_type, subject_uuid)
    runner: QuestionPreviewRunner | None = None
    try:
        runner = QuestionPreviewRunner(team=team, user=user, subject=subject, config=parsed, column_name=column_name)
        return runner.run()
    except Exception as err:
        # The response is sanitized and previews keep no run record, so this is the only trace of the cause.
        # The raw message can carry source values or the question, so only the error class is logged.
        logger.warning(
            "data_quality_question_preview_failed",
            team_id=team.id,
            preview_run_id=runner.run_id if runner else None,
            error_type=type(err).__name__,
        )
        raise CheckConfigError("Could not complete the question preview. Check your access and try again.") from None
