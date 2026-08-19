"""Execute one check and record the result.

Never called in-request: every path into here comes from a Temporal activity, because a check runs
an arbitrary warehouse query and there is no response worth waiting for.

A check that cannot be compiled or executed is recorded as ``errored``, not raised. One broken
check must not take down the rest of its suite.
"""

import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from posthog.hogql.context import HogQLContext
from posthog.hogql.query import execute_hogql_query

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.scoping import team_scope
from posthog.models.team import Team

from ..facade.enums import CheckRunStatus, CheckSeverity, SubjectStatus
from ..models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from .compiler import compile_check, related_subject_ref
from .contracts import CompiledCheck, Evaluation
from .subjects import resolve_subject

QUERY_TYPE = "data_quality_check"


@dataclass(frozen=True)
class CheckOutcome:
    """What one check execution produced, before it is written down."""

    status: CheckRunStatus
    failed_row_count: int | None = None
    observed_value: float | None = None
    compiled_query: str = ""
    error: str = ""
    became_failing: bool = False


def run_check(
    check: DataQualityCheck,
    suite_run: DataQualitySuiteRun,
    team: Team,
    database: "Database | None" = None,
) -> CheckOutcome:
    """Compile, execute, and persist one check. Updates the check's denormalized status.

    Runs under an explicit team scope because there is no request context out here, and saving a
    check reads its own previous state through the fail-closed manager to build the activity log.
    ``database`` overrides table resolution for write-audit-publish runs (see logic/staged_audit).
    """
    started_at = datetime.now(UTC)
    monotonic_start = time.monotonic()
    previous_status = check.last_status

    try:
        outcome = _execute(check, team, database)
    except Exception as err:
        outcome = CheckOutcome(status=CheckRunStatus.ERRORED, error=str(err))

    duration_ms = int((time.monotonic() - monotonic_start) * 1000)
    with team_scope(team.id):
        _record_run(check, suite_run, outcome, started_at, duration_ms)
        _update_check(check, outcome)

    became_failing = (
        outcome.status is CheckRunStatus.FAILED
        and previous_status != CheckRunStatus.FAILED
        and check.severity == CheckSeverity.ERROR
    )
    return replace(outcome, became_failing=became_failing)


def record_unrunnable_check(
    check: DataQualityCheck,
    suite_run: DataQualitySuiteRun,
    team: Team,
    reason: str,
) -> CheckOutcome:
    """A check with no run row reads, in the health state and the API, exactly like one that passed."""
    outcome = CheckOutcome(status=CheckRunStatus.ERRORED, error=reason)
    with team_scope(team.id):
        _record_run(check, suite_run, outcome, datetime.now(UTC), duration_ms=0)
        _update_check(check, outcome)
    return outcome


def _execute(check: DataQualityCheck, team: Team, database: "Database | None" = None) -> CheckOutcome:
    if check.subject_uuid is None:
        check.subject_status = SubjectStatus.ORPHANED
        return CheckOutcome(status=CheckRunStatus.SKIPPED, error="The subject was deleted.")

    subject = resolve_subject(team.id, check.subject_type, check.subject_uuid)
    if not subject.exists:
        check.subject_status = SubjectStatus.ORPHANED
        return CheckOutcome(status=CheckRunStatus.SKIPPED, error="The subject no longer resolves.")

    check.subject_status = SubjectStatus.ACTIVE
    check.subject_name = subject.name

    related = related_subject_ref(check.check_type, check.config)
    compiled = compile_check(
        check_type=check.check_type,
        subject=subject,
        column_name=check.column_name,
        config=check.config,
        related_subject=resolve_subject(team.id, *related) if related else None,
    )
    with tags_context(
        product=Product.DATA_QUALITY,
        feature=Feature.DATA_QUALITY_CHECK,
        data_quality_check_id=str(check.id),
        data_quality_check_type=check.check_type,
        data_quality_subject_type=subject.subject_type,
        data_quality_subject_id=subject.subject_uuid,
    ):
        if database is not None:
            response = execute_hogql_query(
                query=compiled.query,
                team=team,
                query_type=QUERY_TYPE,
                context=HogQLContext(team_id=team.pk, database=database),
            )
        else:
            response = execute_hogql_query(query=compiled.query, team=team, query_type=QUERY_TYPE)
    return _interpret(compiled, check.config, response.results, response.columns or [])


def _interpret(
    compiled: CompiledCheck,
    config: dict[str, Any],
    results: list[Any] | None,
    columns: list[str],
) -> CheckOutcome:
    if not results:
        return CheckOutcome(
            status=CheckRunStatus.ERRORED,
            compiled_query=compiled.printed_failing_rows_query,
            error="The check query returned no rows.",
        )

    row = dict(zip(columns, results[0]))
    observed = _as_float(row.get("observed_value"))

    if compiled.evaluation is Evaluation.BOUNDS:
        status = CheckRunStatus.PASSED if _within_bounds(observed, config) else CheckRunStatus.FAILED
        failed_row_count = None
    else:
        failed_row_count = int(row.get("failure_count") or 0)
        status = CheckRunStatus.PASSED if failed_row_count == 0 else CheckRunStatus.FAILED

    return CheckOutcome(
        status=status,
        failed_row_count=failed_row_count,
        observed_value=observed,
        compiled_query=compiled.printed_failing_rows_query,
    )


def _within_bounds(observed: float | None, config: dict[str, Any]) -> bool:
    if observed is None:
        return False
    minimum, maximum = config.get("min"), config.get("max")
    if minimum is not None and observed < minimum:
        return False
    return not (maximum is not None and observed > maximum)


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _record_run(
    check: DataQualityCheck,
    suite_run: DataQualitySuiteRun,
    outcome: CheckOutcome,
    started_at: datetime,
    duration_ms: int,
) -> None:
    if check.subject_uuid is None:
        return
    DataQualityCheckRun.objects.for_team(check.team_id).create(
        team_id=check.team_id,
        quality_check=check,
        suite_run=suite_run,
        subject_type=check.subject_type,
        subject_uuid=check.subject_uuid,
        subject_name=check.subject_name,
        check_type=check.check_type,
        check_fingerprint=check.fingerprint,
        column_name=check.column_name,
        status=outcome.status,
        failed_row_count=outcome.failed_row_count,
        observed_value=outcome.observed_value,
        compiled_query=outcome.compiled_query,
        error=outcome.error,
        duration_ms=duration_ms,
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )


def _update_check(check: DataQualityCheck, outcome: CheckOutcome) -> None:
    check.last_status = outcome.status
    check.last_run_at = datetime.now(UTC)
    check.save(update_fields=["last_status", "last_run_at", "subject_name", "subject_status", "updated_at"])
