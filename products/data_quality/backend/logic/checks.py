"""Authoring and triggering data quality checks.

Creation is an upsert on the fingerprint (KTD: agents re-propose the same check constantly, and a
duplicate row is worse than a no-op). Everything that runs a check goes through Temporal -- nothing
here waits on a warehouse query.
"""

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User
from posthog.temporal.common.client import sync_connect

from ..facade.contracts import CHECK_SUITE_WORKFLOW_NAME
from ..facade.enums import SubjectHealth, SubjectStatus, SubjectType, SuiteRunStatus, SuiteRunTrigger
from ..models import DataQualityCheck, DataQualitySuiteRun
from .compiler import related_subject_ref
from .errors import DuplicateDefinitionError, NameConflictError, SubjectUnresolvableError
from .exceptions import CheckNameConflict
from .health import CheckStatusRow, roll_up_health
from .registry import get_spec
from .serialization import compute_fingerprint
from .spec import CheckConfig
from .subjects import resolve_subject

_UPSERTABLE_FIELDS = (
    "name",
    "description",
    "severity",
    "enabled",
    "tags",
    "created_source",
    "ai_model",
    "confidence",
    "reasoning",
    "owner",
)

# What the fingerprint hashes: change any of these and the check asserts something else.
_ASSERTION_FIELDS = ("check_type", "column_name", "config")

_EDITABLE_FIELDS = (*_UPSERTABLE_FIELDS, *_ASSERTION_FIELDS)


def _subject_fk(subject_type: str, subject_uuid: str | UUID) -> dict[str, Any]:
    """The FK kwargs for whichever subject kind this is."""
    if subject_type == SubjectType.TABLE:
        return {"table_id": subject_uuid}
    return {"saved_query_id": subject_uuid}


def validate_check(
    team: Team,
    subject_type: str,
    subject_uuid: str,
    check_type: str,
    column_name: str,
    config: dict[str, Any],
) -> CheckConfig:
    """Reject a check the compiler could never run, at authoring time rather than at run time.

    Returns the parsed config so callers do not validate twice, and so the fingerprint hashes the
    normalized form rather than whatever representation the request happened to use.
    """
    parsed = get_spec(check_type).validate(config, column_name)

    if not resolve_subject(team.id, subject_type, subject_uuid).exists:
        raise SubjectUnresolvableError(f"No {subject_type} with id {subject_uuid} in this project.")

    related = related_subject_ref(check_type, config)
    if related and not resolve_subject(team.id, *related).exists:
        raise SubjectUnresolvableError(f"The referenced {related[0]} {related[1]} does not exist.")

    return parsed


def upsert_check(
    *,
    team: Team,
    user: User | None,
    subject_type: str,
    subject_uuid: str,
    check_type: str,
    column_name: str,
    config: dict[str, Any],
    **optional: Any,
) -> tuple[DataQualityCheck, bool]:
    """Create the check, or refine the one already carrying this fingerprint. Returns (check, created)."""
    parsed = validate_check(team, subject_type, subject_uuid, check_type, column_name, config)
    subject = resolve_subject(team.id, subject_type, subject_uuid)

    # Stored in the same canonical form the fingerprint hashes, so a created check and one edited
    # into the same definition are indistinguishable afterwards.
    canonical = parsed.model_dump(mode="json")
    fingerprint = compute_fingerprint(
        subject_type=subject_type,
        subject_uuid=str(subject_uuid),
        check_type=check_type,
        column_name=column_name,
        config=canonical,
    )
    existing = _find_by_fingerprint(team.id, subject_type, subject_uuid, fingerprint)
    fields = {key: value for key, value in optional.items() if key in _UPSERTABLE_FIELDS and value is not None}

    # Checked here rather than before the fingerprint lookup: re-proposing an identical named check
    # must upsert, and a name conflict with *itself* is not a conflict.
    ensure_name_available(team.id, fields.get("name") or "", exclude_id=existing.id if existing else None)

    if existing is None:
        try:
            # Savepoint so a lost race rolls back cleanly instead of poisoning an outer transaction.
            with transaction.atomic():
                check = DataQualityCheck.objects.for_team(team.id).create(
                    team=team,
                    created_by=user,
                    subject_type=subject_type,
                    subject_name=subject.name,
                    subject_status=SubjectStatus.ACTIVE,
                    check_type=check_type,
                    column_name=column_name,
                    config=canonical,
                    fingerprint=fingerprint,
                    **_subject_fk(subject_type, subject_uuid),
                    **fields,
                )
            return check, True
        except IntegrityError:
            # Check-then-insert race: a concurrent identical request inserted this fingerprint between
            # the lookup above and this create. Refetch and refine the row it won with, so the loser
            # gets the promised existing check (HTTP 200) rather than a 500.
            existing = _find_by_fingerprint(team.id, subject_type, subject_uuid, fingerprint)
            if existing is None:
                # The name constraint races the same way, past its own precheck, so report it as the
                # conflict it is rather than letting the database error surface as a 500.
                ensure_name_available(team.id, fields.get("name") or "")
                raise

    return update_check(existing, **fields), False


def _find_by_fingerprint(
    team_id: int, subject_type: str, subject_uuid: str, fingerprint: str
) -> DataQualityCheck | None:
    """The *active* check carrying this fingerprint, if any.

    Active-only so authoring a definition that was deleted earlier creates a new check with its own
    id and history, rather than resurrecting a row the user believes is gone.
    """
    return (
        DataQualityCheck.objects.for_team(team_id)
        .filter(fingerprint=fingerprint, deleted=False, **_subject_fk(subject_type, subject_uuid))
        .first()
    )


def update_check(check: DataQualityCheck, **fields: Any) -> DataQualityCheck:
    """Apply presentation changes only. Editing the assertion goes through ``edit_check``."""
    changed = [key for key in fields if key in _UPSERTABLE_FIELDS]
    for key in changed:
        setattr(check, key, fields[key])

    if changed:
        check.save(update_fields=[*changed, "updated_at"])
    return check


@frozen
class _CandidateDefinition:
    """What a requested edit would leave the check asserting, canonicalized."""

    check_type: str
    column_name: str
    config: dict[str, Any]
    fingerprint: str


def edit_check(*, team: Team, check: DataQualityCheck, editor: User | None, **fields: Any) -> DataQualityCheck:
    """Save a complete definition change, or none of it. The owning subject never moves.

    Two edits to the same check serialize on the row lock, so the loser recomputes against what the
    winner committed. Two *different* rows converging on one definition race past that lock, and the
    active-fingerprint constraint is what settles them -- its ``IntegrityError`` comes back as the
    same conflict the precheck raises.
    """
    requested = {key: value for key, value in fields.items() if key in _EDITABLE_FIELDS}
    try:
        with transaction.atomic():
            locked = DataQualityCheck.objects.for_team(team.id).select_for_update().get(id=check.id)
            return _commit_edit(team, locked, editor, requested)
    except IntegrityError:
        # Which constraint lost decides which field the error is addressed to. Asking about the
        # definition alone would answer "duplicate" for every one of them, since an edit that leaves
        # the assertion alone still finds its own fingerprint.
        candidate = _candidate_definition(team, check, requested)
        if _definition_taken(check, candidate.fingerprint):
            raise DuplicateDefinitionError()
        if _name_taken(team.id, requested.get("name") or "", exclude_id=check.id):
            raise NameConflictError()
        raise


def _commit_edit(
    team: Team, check: DataQualityCheck, editor: User | None, requested: dict[str, Any]
) -> DataQualityCheck:
    candidate = _candidate_definition(team, check, requested)
    _ensure_definition_available(check, candidate.fingerprint)
    if _name_taken(team.id, requested.get("name") or "", exclude_id=check.id):
        raise NameConflictError()

    changed = {key for key in requested if key in _UPSERTABLE_FIELDS}
    for key in changed:
        setattr(check, key, requested[key])

    if candidate.fingerprint != check.fingerprint:
        check.check_type = candidate.check_type
        check.column_name = candidate.column_name
        check.config = candidate.config
        check.fingerprint = candidate.fingerprint
        # An automated run of an edited definition authorizes as whoever last changed what it reads,
        # not as whoever created it years ago.
        check.definition_author = editor
        changed |= {*_ASSERTION_FIELDS, "fingerprint", "definition_author"}

    if changed:
        check.save(update_fields=[*changed, "updated_at"])
    return check


def _candidate_definition(team: Team, check: DataQualityCheck, requested: dict[str, Any]) -> _CandidateDefinition:
    check_type = requested.get("check_type", check.check_type)
    column_name = requested.get("column_name", check.column_name)
    parsed = validate_check(
        team,
        check.subject_type,
        str(check.subject_uuid),
        check_type,
        column_name,
        requested.get("config", check.config) or {},
    )
    config = parsed.model_dump(mode="json")
    return _CandidateDefinition(
        check_type=check_type,
        column_name=column_name,
        config=config,
        fingerprint=compute_fingerprint(
            subject_type=check.subject_type,
            subject_uuid=str(check.subject_uuid),
            check_type=check_type,
            column_name=column_name,
            config=config,
        ),
    )


def _definition_taken(check: DataQualityCheck, fingerprint: str) -> bool:
    """Whether *another* active check on this subject already asserts this."""
    return (
        DataQualityCheck.objects.for_team(check.team_id)
        .filter(fingerprint=fingerprint, deleted=False, **_subject_fk(check.subject_type, str(check.subject_uuid)))
        .exclude(id=check.id)
        .exists()
    )


def _ensure_definition_available(check: DataQualityCheck, fingerprint: str) -> None:
    if _definition_taken(check, fingerprint):
        raise DuplicateDefinitionError()


def soft_delete_check(check: DataQualityCheck) -> None:
    """Hide the definition but keep its run history queryable."""
    check.deleted = True
    check.deleted_at = datetime.now(UTC)
    check.enabled = False
    check.save(update_fields=["deleted", "deleted_at", "enabled", "updated_at"])


def checks_for_subject(
    team_id: int, subject_type: str, subject_uuid: str | UUID, include_deleted: bool = False
) -> QuerySet[DataQualityCheck]:
    queryset = DataQualityCheck.objects.for_team(team_id).filter(**_subject_fk(subject_type, subject_uuid))
    # A soft-deleted check's past runs still sit in the aggregate counts of suites it ran in, so
    # authorization over a *historical* suite has to see it too, even though it no longer runs.
    return queryset if include_deleted else queryset.filter(deleted=False)


def subject_health(team_id: int, subject_type: str, subject_uuid: str | UUID) -> SubjectHealth:
    # Only enabled checks count toward health, matching the REST counts and the
    # information_schema.data_quality_health table -- the three must never disagree.
    rows = (
        checks_for_subject(team_id, subject_type, subject_uuid)
        .filter(enabled=True)
        .values_list("severity", "last_status")
    )
    return roll_up_health(CheckStatusRow(severity=severity, last_status=status) for severity, status in rows)


def start_check_suite(
    *,
    team: Team,
    trigger: SuiteRunTrigger = SuiteRunTrigger.MANUAL,
    user: User | None = None,
    subject_type: str = "",
    subject_uuids: list[str] | None = None,
    check_ids: list[str] | None = None,
) -> DataQualitySuiteRun:
    """Kick off a suite run and hand back the row to poll.

    The row is created here rather than inside the workflow so the caller gets a pollable handle
    synchronously; the prepare activity fills in the batches.
    """
    # Deferred: importing anything under ``temporal`` executes its package __init__, which pulls
    # the workflow and activity modules (and temporalio's sandbox) onto the request import path.
    from ..temporal.contracts import RunCheckSuiteInputs  # noqa: PLC0415

    subject_uuids = subject_uuids or []
    suite_run = DataQualitySuiteRun.objects.for_team(team.id).create(
        team=team,
        trigger=trigger,
        created_by=user,
        subject_type=subject_type if len(subject_uuids) == 1 else "",
        subject_uuid=subject_uuids[0] if len(subject_uuids) == 1 else None,
        workflow_id=f"data-quality-run-suite-{team.id}-{uuid4()}",
        started_at=datetime.now(UTC),
    )
    inputs = RunCheckSuiteInputs(
        team_id=team.id,
        trigger=trigger,
        saved_query_ids=subject_uuids if subject_type == SubjectType.VIEW else [],
        table_ids=subject_uuids if subject_type == SubjectType.TABLE else [],
        check_ids=check_ids or [],
        suite_run_id=str(suite_run.id),
        created_by_id=user.id if user else None,
    )
    try:
        temporal = sync_connect()
        asyncio.run(
            temporal.start_workflow(
                CHECK_SUITE_WORKFLOW_NAME,
                asdict(inputs),
                id=suite_run.workflow_id,
                task_queue=str(settings.DATA_MODELING_TASK_QUEUE),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        )
    except Exception as err:
        # The row is already committed, so leaving it would report `running` forever with no
        # workflow behind it. Close it out before surfacing the error to the caller.
        suite_run.status = SuiteRunStatus.FAILED
        suite_run.error = str(err)
        suite_run.finished_at = datetime.now(UTC)
        suite_run.save(update_fields=["status", "error", "finished_at", "updated_at"])
        raise

    return suite_run


def empty_check_suite(*, team: Team, user: User | None = None) -> DataQualitySuiteRun:
    """Record a run that had nothing to run, without starting a workflow.

    An empty selection cannot be expressed to the worker: by the time ``check_ids`` reaches the
    prepare activity, an empty list is indistinguishable from no selector at all, and the suite
    would sweep the whole project.
    """
    now = datetime.now(UTC)
    return DataQualitySuiteRun.objects.for_team(team.id).create(
        team=team,
        trigger=SuiteRunTrigger.MANUAL,
        created_by=user,
        status=SuiteRunStatus.EMPTY,
        started_at=now,
        finished_at=now,
    )


def _name_taken(team_id: int, name: str, exclude_id: UUID | str | None = None) -> bool:
    """Whether an *active* check already holds this name. Deleted ones keep theirs only as history."""
    if not name:
        return False
    clashes = DataQualityCheck.objects.for_team(team_id).filter(name=name, deleted=False)
    if exclude_id is not None:
        clashes = clashes.exclude(id=exclude_id)
    return clashes.exists()


def ensure_name_available(team_id: int, name: str, exclude_id: UUID | str | None = None) -> None:
    if _name_taken(team_id, name, exclude_id):
        raise CheckNameConflict(f"A check named '{name}' already exists in this project.")
