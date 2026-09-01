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
from posthog.models.user import User

from ..facade.enums import CheckRunStatus, CheckSeverity, SubjectStatus, SuiteRunTrigger
from ..models import DataQualityCheck, DataQualitySuiteRun
from .compiler import compile_check, related_subject_ref
from .contracts import CompiledCheck, Evaluation
from .notifications import notify_check_started_failing
from .run_records import record_check_run
from .staged_audit import StagedSubjectOverride, build_staged_database
from .subject_access import check_type_reads_beyond_subject, pin_referenced_subjects
from .subjects import resolve_subject

QUERY_TYPE = "data_quality_check"

STAGED_FILES_UNREADABLE = "The staged files could not be read, so this data was not audited."


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
    staged: StagedSubjectOverride | None = None,
    staged_database_cache: "dict[Any, Database | None] | None" = None,
) -> CheckOutcome:
    """Compile, execute, and persist one check. Updates the check's denormalized status.

    Runs under an explicit team scope because there is no request context out here, and saving a
    check reads its own previous state through the fail-closed manager to build the activity log.
    ``staged`` redirects the subject's table at unpublished files for write-audit-publish runs (see
    logic/staged_audit); the cache is shared across a batch so each ACL posture builds one database.
    """
    started_at = datetime.now(UTC)
    monotonic_start = time.monotonic()

    try:
        outcome = _execute(check, suite_run, team, staged, staged_database_cache)
    except Exception as err:
        outcome = CheckOutcome(status=CheckRunStatus.ERRORED, error=str(err))

    duration_ms = int((time.monotonic() - monotonic_start) * 1000)
    with team_scope(team.id):
        _record_run(check, suite_run, outcome, started_at, duration_ms)
        became_failing = (
            outcome.status is CheckRunStatus.FAILED
            and check.severity == CheckSeverity.ERROR
            and _claim_failing_transition(check)
        )
        _update_check(check, outcome)

    if became_failing:
        notify_check_started_failing(check, outcome.failed_row_count)
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


def _claim_failing_transition(check: DataQualityCheck) -> bool:
    """Whether this run is the one that moved the check into failing.

    Runs of the same check can overlap -- a manual run alongside the scheduled one -- and comparing
    against a status read in Python lets both of them see the same passing value and notify. The
    conditional update lets exactly one flip the row, so the pass-to-fail edge notifies once. Must
    run before ``_update_check`` writes the new status, or there is nothing left to claim.
    """
    return (
        DataQualityCheck.objects.for_team(check.team_id)
        .filter(id=check.id)
        .exclude(last_status=CheckRunStatus.FAILED)
        .update(last_status=CheckRunStatus.FAILED)
        == 1
    )


@dataclass(frozen=True)
class _Authorization:
    """How one run's query executes against warehouse access control."""

    run_as: User | None
    bypass: bool


def _authorize(check: DataQualityCheck, suite_run: DataQualitySuiteRun) -> _Authorization | None:
    """How a run's query must execute so HogQL enforces the right warehouse access control.

    A check that reads beyond its declared subject -- ``custom_sql`` runs arbitrary HogQL,
    ``relationships`` also reads its target subject -- can otherwise be used to read a failing-row
    count over a table the caller was denied. The defense is to run the query as a user whose
    warehouse ACL HogQL will apply, so a denied object errors the check instead of leaking.

    - Manual runs execute as their initiator.
    - Automated runs (materialization, source sync) have no initiator. A check constrained to only
      its declared subject exposes nothing the definition doesn't already name, so the service
      bypass is safe. A check that reads a further subject has no such guarantee, so it executes as
      whoever last authored the definition -- the creator only until someone edits it, since after
      an edit it is the editor who was authorized against what it now reads. With nobody to
      authorize against, returning ``None`` errors the run rather than bypassing the ACL.
    """
    if suite_run.trigger == SuiteRunTrigger.MANUAL:
        return _Authorization(run_as=suite_run.created_by, bypass=suite_run.created_by is None)
    if not check_type_reads_beyond_subject(check.check_type):
        return _Authorization(run_as=None, bypass=True)
    principal = check.definition_author or check.created_by
    if principal is None:
        return None
    return _Authorization(run_as=principal, bypass=False)


def _staged_database(
    team: Team,
    staged: StagedSubjectOverride,
    authorization: _Authorization,
    cache: "dict[Any, Database | None] | None",
) -> "Database | None":
    """The staged-override database for this run's ACL posture, built once per posture per batch."""
    key = authorization.run_as.id if authorization.run_as is not None else "__bypass__"
    if cache is not None and key in cache:
        return cache[key]
    database = build_staged_database(
        team,
        staged.saved_query_id,
        staged.queryable_folder,
        user=authorization.run_as,
        bypass_warehouse_access_control=authorization.bypass,
    )
    if cache is not None:
        cache[key] = database
    return database


def staged_subject_is_reachable(
    team: Team,
    staged: StagedSubjectOverride,
    cache: "dict[Any, Database | None] | None" = None,
) -> bool:
    """Whether the staged files can be repointed at all, before any check runs.

    Independent of which user a check executes as, so a batch settles it once. Shares the runner's
    cache, so the database built here is the one the service-bypass runs reuse.
    """
    return _staged_database(team, staged, _Authorization(run_as=None, bypass=True), cache) is not None


def _execute(
    check: DataQualityCheck,
    suite_run: DataQualitySuiteRun,
    team: Team,
    staged: StagedSubjectOverride | None = None,
    staged_database_cache: "dict[Any, Database | None] | None" = None,
) -> CheckOutcome:
    # A hard-deleted subject nulls the FK; there is no id left to resolve.
    if check.subject_uuid is None:
        check.subject_status = SubjectStatus.ORPHANED
        return CheckOutcome(status=CheckRunStatus.SKIPPED, error="The subject was deleted.")

    subject = resolve_subject(team.id, check.subject_type, check.subject_uuid)
    if not subject.exists:
        check.subject_status = SubjectStatus.ORPHANED
        return CheckOutcome(status=CheckRunStatus.SKIPPED, error="The subject no longer resolves.")

    check.subject_status = SubjectStatus.ACTIVE
    check.subject_name = subject.name

    authorization = _authorize(check, suite_run)
    if authorization is None:
        return CheckOutcome(
            status=CheckRunStatus.ERRORED,
            error="An automated check that reads another subject needs an author to authorize its warehouse access.",
        )

    related = related_subject_ref(check.check_type, check.config)
    compiled = compile_check(
        check_type=check.check_type,
        subject=subject,
        column_name=check.column_name,
        config=check.config,
        related_subject=resolve_subject(team.id, *related) if related else None,
    )
    database = _staged_database(team, staged, authorization, staged_database_cache) if staged is not None else None
    if staged is not None and database is None:
        # Falling back to the unmodified database would read the live view and rule on data the
        # publish would not write, so a staged run that cannot repoint errors instead.
        return CheckOutcome(status=CheckRunStatus.ERRORED, error=STAGED_FILES_UNREADABLE)

    with tags_context(
        product=Product.DATA_QUALITY,
        feature=Feature.DATA_QUALITY_CHECK,
        data_quality_check_id=str(check.id),
        data_quality_check_type=check.check_type,
        data_quality_subject_type=subject.subject_type,
        data_quality_subject_id=subject.subject_uuid,
    ):
        # The query runs as the user whose warehouse ACL HogQL should enforce (see _authorize). The
        # service-level bypass is only used where there is no actor and the query is constrained to
        # the check's declared subject, so it can't reach a warehouse object the definition doesn't
        # already name.
        if database is not None:
            response = execute_hogql_query(
                query=compiled.query,
                team=team,
                query_type=QUERY_TYPE,
                context=HogQLContext(
                    team_id=team.pk,
                    user=authorization.run_as,
                    database=database,
                    bypass_warehouse_access_control=authorization.bypass,
                ),
            )
        else:
            response = execute_hogql_query(
                query=compiled.query,
                team=team,
                query_type=QUERY_TYPE,
                user=authorization.run_as,
                bypass_warehouse_access_control=authorization.bypass,
            )
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
    record_check_run(
        check.team_id,
        quality_check=check,
        suite_run=suite_run,
        subject_type=check.subject_type,
        subject_uuid=check.subject_uuid,
        subject_name=check.subject_name,
        check_type=check.check_type,
        check_fingerprint=check.fingerprint,
        column_name=check.column_name,
        check_config=check.config,
        check_severity=check.severity,
        referenced_subjects=pin_referenced_subjects(check.team_id, check.check_type, check.config),
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
    updated = ["last_status", "last_run_at", "subject_name", "subject_status", "updated_at"]
    if outcome.status is CheckRunStatus.PASSED:
        check.last_succeeded_at = check.last_run_at
        # Written only by the run that earned it. A failing run holds whatever this row said when its
        # batch loaded it, so listing the column unconditionally would let it overwrite a success a
        # concurrent run committed in between.
        updated.append("last_succeeded_at")
    check.save(update_fields=updated)
