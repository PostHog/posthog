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
from django.db.models import QuerySet

from temporalio.common import RetryPolicy

from posthog.models.team import Team
from posthog.models.user import User
from posthog.temporal.common.client import sync_connect

from ..facade.contracts import CHECK_SUITE_WORKFLOW_NAME
from ..facade.enums import SubjectHealth, SubjectStatus, SuiteRunStatus, SuiteRunTrigger
from ..models import DataQualityCheck, DataQualitySuiteRun
from .compiler import related_subject_ref
from .errors import SubjectUnresolvableError
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
    "run_on_materialization",
    "schedule_interval_minutes",
    "created_source",
    "ai_model",
    "confidence",
    "reasoning",
    "owner",
)


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

    fingerprint = compute_fingerprint(
        subject_type=subject_type,
        subject_uuid=str(subject_uuid),
        check_type=check_type,
        column_name=column_name,
        config=parsed.model_dump(mode="json"),
    )
    existing = (
        DataQualityCheck.objects.for_team(team.id)
        .filter(subject_type=subject_type, subject_uuid=subject_uuid, fingerprint=fingerprint)
        .first()
    )
    fields = {key: value for key, value in optional.items() if key in _UPSERTABLE_FIELDS and value is not None}

    # Checked here rather than before the fingerprint lookup: re-proposing an identical named check
    # must upsert, and a name conflict with *itself* is not a conflict.
    ensure_name_available(team.id, fields.get("name") or "", exclude_id=existing.id if existing else None)

    if existing is None:
        check = DataQualityCheck.objects.for_team(team.id).create(
            team=team,
            created_by=user,
            subject_type=subject_type,
            subject_uuid=subject_uuid,
            subject_name=subject.name,
            subject_status=SubjectStatus.ACTIVE,
            check_type=check_type,
            column_name=column_name,
            config=config,
            fingerprint=fingerprint,
            next_run_at=_initial_next_run_at(fields.get("schedule_interval_minutes")),
            **fields,
        )
        return check, True

    return update_check(existing, **fields, deleted=False), False


def update_check(check: DataQualityCheck, **fields: Any) -> DataQualityCheck:
    """Apply presentation and scheduling changes. The assertion itself is immutable -- re-create instead."""
    changed = []
    for key, value in fields.items():
        if key in _UPSERTABLE_FIELDS or key == "deleted":
            setattr(check, key, value)
            changed.append(key)

    if "schedule_interval_minutes" in changed:
        check.next_run_at = _initial_next_run_at(check.schedule_interval_minutes)
        changed.append("next_run_at")

    if changed:
        check.save(update_fields=[*changed, "updated_at"])
    return check


def soft_delete_check(check: DataQualityCheck) -> None:
    """Hide the definition but keep its run history queryable."""
    check.deleted = True
    check.deleted_at = datetime.now(UTC)
    check.enabled = False
    check.next_run_at = None
    check.save(update_fields=["deleted", "deleted_at", "enabled", "next_run_at", "updated_at"])


def checks_for_subject(team_id: int, subject_type: str, subject_uuid: str | UUID) -> QuerySet[DataQualityCheck]:
    return DataQualityCheck.objects.for_team(team_id).filter(
        subject_type=subject_type, subject_uuid=subject_uuid, deleted=False
    )


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
    trigger: str = SuiteRunTrigger.MANUAL,
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
        subject_type=subject_type,
        subject_uuids=subject_uuids,
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


def ensure_name_available(team_id: int, name: str, exclude_id: UUID | str | None = None) -> None:
    if not name:
        return
    clashes = DataQualityCheck.objects.for_team(team_id).filter(name=name)
    if exclude_id is not None:
        clashes = clashes.exclude(id=exclude_id)
    if clashes.exists():
        raise CheckNameConflict(f"A check named '{name}' already exists in this project.")


def _initial_next_run_at(schedule_interval_minutes: int | None) -> datetime | None:
    """Scheduled checks are due immediately; the scanner advances them onto the cadence grid."""
    return datetime.now(UTC) if schedule_interval_minutes else None
