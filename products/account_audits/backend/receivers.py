from typing import Protocol
from uuid import UUID

from django.db import transaction

from products.account_audits.backend.models import AccountAuditAdmission
from products.tasks.backend.facade.task_run_signals import connect_task_run_post_save


class AuditRunSave(Protocol):
    id: UUID
    team_id: int
    status: str


def schedule_audit_completion(
    sender: type, instance: AuditRunSave, created: bool, update_fields: frozenset[str] | None = None, **kwargs: object
) -> None:
    if created or instance.status not in {"completed", "failed", "cancelled"}:
        return
    if update_fields is not None and not {"status", "output", "state"}.intersection(update_fields):
        return
    if not AccountAuditAdmission.objects.for_team(instance.team_id).filter(task_run_id=instance.id).exists():
        return
    from products.account_audits.backend.tasks.tasks import (  # noqa: PLC0415 — keeps Celery off Django startup
        finalize_account_audit,
    )

    transaction.on_commit(lambda: finalize_account_audit.delay(instance.team_id, str(instance.id)), robust=True)


def connect() -> None:
    connect_task_run_post_save(schedule_audit_completion, dispatch_uid="account_audits_finalize_account_audit")
