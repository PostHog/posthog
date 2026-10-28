from django.db import transaction
from django.db.models import Q, Sum

from rest_framework.exceptions import ValidationError

from ..db import WRITER_DB
from ..facade.contracts import Money
from ..facade.enums import LedgerKind
from ..models import Bet, BetsSettings, LedgerEntry, WorkItem


def totals(team_id: int, bet: Bet | None = None, work: WorkItem | None = None) -> Money:
    rows = LedgerEntry.objects.for_team(team_id, canonical=True).using(WRITER_DB)
    if bet is not None:
        rows = rows.filter(bet=bet)
    if work is not None:
        rows = rows.filter(work_item=work)
    sums = {row["kind"]: row["total"] for row in rows.values("kind").annotate(total=Sum("amount_cents"))}
    allocated = sums.get("allocate", 0) - sums.get("deallocate", 0)
    spent = sums.get("spend", 0)
    reservations = rows.values("bet_id", "work_item_id").annotate(
        held=Sum("amount_cents", filter=Q(kind=LedgerKind.RESERVE), default=0),
        released=Sum("amount_cents", filter=Q(kind=LedgerKind.RELEASE), default=0),
        settled=Sum("amount_cents", filter=Q(kind=LedgerKind.SPEND), default=0),
    )
    reserved = sum(max(0, row["held"] - row["released"] - row["settled"]) for row in reservations)
    if bet is None and work is None:
        # Late provider charges still consume the project budget after a bet has released its allocation.
        commitments = rows.values("bet_id").annotate(
            assigned=Sum("amount_cents", filter=Q(kind=LedgerKind.ALLOCATE), default=0),
            returned=Sum("amount_cents", filter=Q(kind=LedgerKind.DEALLOCATE), default=0),
            charged=Sum("amount_cents", filter=Q(kind=LedgerKind.SPEND), default=0),
        )
        held_by_bet: dict = {}
        for row in reservations:
            held_by_bet[row["bet_id"]] = held_by_bet.get(row["bet_id"], 0) + max(
                0, row["held"] - row["released"] - row["settled"]
            )
        allocated = sum(
            max(row["assigned"] - row["returned"], row["charged"] + held_by_bet.get(row["bet_id"], 0))
            for row in commitments
        )
    return Money(
        allocated_cents=allocated,
        spent_cents=spent,
        reserved_cents=reserved,
        available_cents=allocated - spent - reserved,
    )


@transaction.atomic(using=WRITER_DB)
def append(
    settings: BetsSettings,
    bet: Bet,
    kind: LedgerKind,
    amount: int,
    key: str,
    actor_id: int | None = None,
    work: WorkItem | None = None,
    source_ref: str = "",
) -> None:
    if settings.team_id != bet.team_id:
        raise ValidationError("The budget belongs to another project.")
    settings = BetsSettings.objects.for_team(bet.team_id).using(WRITER_DB).select_for_update().get(id=settings.id)
    entries = LedgerEntry.objects.for_team(bet.team_id, canonical=True).using(WRITER_DB)
    existing = entries.filter(key=key).first()
    if existing:
        if (
            existing.bet_id != bet.id
            or existing.kind != kind
            or existing.amount_cents != amount
            or existing.work_item_id != (work.id if work else None)
        ):
            raise ValidationError("This operation key was already used for a different budget change.")
        return
    if amount < 0:
        raise ValidationError("Budget amounts must not be negative.")
    if kind == LedgerKind.RESERVE and work is None:
        raise ValidationError("A reservation must belong to a work item.")
    current = totals(bet.team_id, bet)
    if kind == LedgerKind.ALLOCATE and totals(bet.team_id).allocated_cents + amount > settings.budget_cents:
        raise ValidationError("This allocation exceeds the available project budget.")
    if kind in (LedgerKind.DEALLOCATE, LedgerKind.RESERVE) and amount > current.available_cents:
        raise ValidationError("This amount exceeds the bet’s available budget.")
    if kind in (LedgerKind.SPEND, LedgerKind.RELEASE):
        if work is None or amount > totals(bet.team_id, work=work).reserved_cents:
            raise ValidationError("This amount exceeds the work reservation.")
    if work is not None and (work.bet_id != bet.id or work.team_id != bet.team_id):
        raise ValidationError("The work item belongs to another bet.")
    entries.create(
        team_id=bet.team_id,
        bet=bet,
        work_item=work,
        kind=kind,
        amount_cents=amount,
        key=key,
        actor_id=actor_id,
        source_ref=source_ref,
    )


@transaction.atomic(using=WRITER_DB)
def settle_usage(bet: Bet, source: str, cumulative_cents: int, work: WorkItem | None = None) -> None:
    if cumulative_cents < 0 or (work is not None and (work.bet_id != bet.id or work.team_id != bet.team_id)):
        raise ValidationError("Invalid usage settlement.")
    BetsSettings.objects.for_team(bet.team_id).using(WRITER_DB).select_for_update().get(team_id=bet.team_id)
    rows = LedgerEntry.objects.for_team(bet.team_id).using(WRITER_DB).filter(bet=bet, source_ref=source)
    settled = rows.filter(kind=LedgerKind.SPEND).aggregate(total=Sum("amount_cents"))["total"] or 0
    if cumulative_cents <= settled:
        return
    # An incurred provider charge must remain visible even if it arrives after the bet closes or exceeds its allocation.
    LedgerEntry.objects.for_team(bet.team_id).using(WRITER_DB).create(
        team_id=bet.team_id,
        bet=bet,
        work_item=work,
        kind=LedgerKind.SPEND,
        amount_cents=cumulative_cents - settled,
        key=f"usage:{bet.id}:{source}:{cumulative_cents}",
        source_ref=source,
    )


def used_up(money: Money) -> bool:
    return money.available_cents <= 0 and money.reserved_cents <= 0
