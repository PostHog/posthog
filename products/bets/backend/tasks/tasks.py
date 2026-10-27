from uuid import UUID

from django.db.models import F, Q, Sum
from django.utils import timezone

from celery import shared_task


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=5, ignore_result=True)
def reconcile_bet_run(team_id: int, run_id: str) -> None:
    from ..facade.api import reconcile_run  # noqa: PLC0415 — keeps the product facade off Celery startup

    reconcile_run(team_id, UUID(run_id))


@shared_task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    ignore_result=True,
    soft_time_limit=540,
    time_limit=600,
    acks_late=True,
    reject_on_worker_lost=True,
)
def coordinate_bet(team_id: int, bet_id: str) -> None:
    from ..logic.loop import reconcile  # noqa: PLC0415 - Celery registers this task without importing product services

    reconcile(team_id, UUID(bet_id))


@shared_task(ignore_result=True)
def reconcile_bets() -> None:
    from ..db import WRITER_DB  # noqa: PLC0415 - periodic registration keeps model imports off Celery startup
    from ..models import (  # noqa: PLC0415 - periodic registration keeps model imports off Celery startup
        Bet,
        LedgerEntry,
    )

    due = Q(reconcile_after__isnull=True) | Q(reconcile_after__lte=timezone.now())
    holding = (
        LedgerEntry.objects.unscoped()
        .using(WRITER_DB)
        .exclude(work_item=None)
        .exclude(bet__status__in=["setting_up", "running"])
        .values("bet_id", "work_item_id")
        .annotate(
            held=Sum("amount_cents", filter=Q(kind="reserve"), default=0),
            returned=Sum("amount_cents", filter=Q(kind__in=["release", "spend"]), default=0),
        )
        .filter(held__gt=F("returned"))
        .values_list("bet_id", flat=True)
    )
    for team_id, bet_id in (
        Bet.objects.unscoped()
        .using(WRITER_DB)
        .filter(Q(status__in=["setting_up", "running"]) | Q(id__in=list(holding)))
        .filter(due)
        .values_list("team_id", "id")
        .iterator(chunk_size=200)
    ):
        coordinate_bet.delay(team_id, str(bet_id))
