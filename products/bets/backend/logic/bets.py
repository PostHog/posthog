from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from ..db import WRITER_DB
from ..facade.enums import BetDirection, BetStatus, LedgerKind, WorkStage
from ..models import Bet, BetsSettings, LedgerEntry, WorkItem
from .ledger import append, totals
from .loop import add_owner_idea, end_experiment, finish, freeze
from .metrics import metric, validate_goal
from .stages import OPEN
from .state import meets, number
from .workspace import get_settings, project_id

if TYPE_CHECKING:
    from posthog.models import Team, User

GOAL_FIELDS = frozenset({"goal_insight", "goal_description", "goal_metric", "secondary_metrics", "repositories"})
TARGET_FIELDS = frozenset({"target", "direction"})
FROZEN_FIELDS = ("final_value", "final_at", "final_series", "reached_at")


def locked_settings(team_id: int) -> BetsSettings:
    return BetsSettings.objects.for_team(team_id).using(WRITER_DB).select_for_update().get(id=get_settings(team_id).id)


def validate_insights(team: Team, user: User, data: dict) -> None:
    if data.get("goal_insight"):
        validate_goal(team, user, data["goal_insight"])
    for secondary in data.get("secondary_metrics", []):
        validate_goal(team, user, secondary["insight"])


def refuse_met_target(team: Team, user: User, data: dict, bet: Bet | None = None) -> None:
    keys = ("goal_insight", "target", "direction")
    if bet is not None and not any(key in data and data[key] != getattr(bet, key) for key in keys):
        return
    insight = data.get("goal_insight", bet.goal_insight if bet else "")
    target = data.get("target", bet.target if bet else None)
    if not insight or target is None:
        return
    value = metric(team, user, insight, complete=True).current
    if value is None and bet is not None and insight == bet.goal_insight:
        value = bet.baseline_value
    probe = Bet(target=target, direction=data.get("direction", bet.direction if bet else BetDirection.INCREASE))
    if meets(probe, value):
        raise ValidationError(
            {
                "target": f"The goal is already at {number(value or 0)}, which meets this target. Set a target the ideas still have to reach."
            }
        )


def reopen(bet: Bet) -> None:
    bet.final_value = None
    bet.final_at = None
    bet.final_series = {}
    bet.reached_at = None


def create_bet(team: Team, user: User, data: dict) -> Bet:
    team_id = project_id(team)
    validate_insights(team, user, data)
    refuse_met_target(team, user, data)
    payload = dict(data)
    budget = payload.pop("budget_cents")
    operation_id = payload.pop("operation_id")
    ideas = [idea for idea in payload.pop("ideas", None) or [] if idea.strip()]
    with transaction.atomic(using=WRITER_DB):
        settings = locked_settings(team_id)
        existing = Bet.objects.for_team(team_id).using(WRITER_DB).filter(id=operation_id).first()
        if existing:
            allocation = LedgerEntry.objects.for_team(team_id).using(WRITER_DB).get(key=f"create:{operation_id}")
            if allocation.amount_cents != budget or existing.owner_id != user.id:
                raise ValidationError("This creation ID already belongs to a different bet.")
            return existing
        bet = (
            Bet.objects.for_team(team_id)
            .using(WRITER_DB)
            .create(team_id=team_id, id=operation_id, owner_id=user.id, reference=settings.next_reference, **payload)
        )
        settings.next_reference += 1
        settings.save(using=WRITER_DB, update_fields=["next_reference", "updated_at"])
        append(settings, bet, LedgerKind.ALLOCATE, budget, f"create:{operation_id}", user.id)
        for idea in ideas:
            add_owner_idea(bet, idea)
        return bet


def update_bet(team: Team, user: User, bet_id: UUID, data: dict) -> Bet:
    team_id = project_id(team)
    validate_insights(team, user, data)
    refuse_met_target(team, user, data, Bet.objects.for_team(team_id).using(WRITER_DB).get(id=bet_id))
    with transaction.atomic(using=WRITER_DB):
        settings = locked_settings(team_id)
        bet = Bet.objects.for_team(team_id).using(WRITER_DB).select_for_update().get(id=bet_id)
        if bet.status == BetStatus.CLOSED:
            raise ValidationError("This bet is closed.")
        payload = dict(data)
        budget = payload.pop("budget_cents", None)
        payload.pop("operation_id", None)
        payload.pop("ideas", None)
        if "repositories" in payload and not bet.repositories:
            bet.repositories = [bet.repository]
        first_target = (
            bet.target is None
            and bet.goal_insight
            and payload.get("goal_insight", bet.goal_insight) == bet.goal_insight
        )
        changed = {key for key in GOAL_FIELDS | TARGET_FIELDS if key in payload and payload[key] != getattr(bet, key)}
        goal_changed = bool(changed - TARGET_FIELDS - ({"goal_metric"} if first_target else set()))
        for field, value in payload.items():
            setattr(bet, field, value)
        if changed & TARGET_FIELDS and not goal_changed:
            bet.goal_met_since = None
            if bet.status == BetStatus.REACHED:
                bet.status = BetStatus.RUNNING if bet.baseline_at else BetStatus.SETTING_UP
                reopen(bet)
        if goal_changed:
            ended = list(
                WorkItem.objects.for_team(team_id)
                .using(WRITER_DB)
                .filter(bet=bet, stage__in=OPEN, experiment_id__isnull=False)
            )
            WorkItem.objects.for_team(team_id).using(WRITER_DB).filter(bet=bet, stage__in=OPEN).update(
                stage=WorkStage.DROPPED, note="The goal changed.", finished_at=timezone.now()
            )
            for work in ended:
                transaction.on_commit(partial(end_experiment, bet, work), using=WRITER_DB)
            bet.goal_version += 1
            bet.status = BetStatus.SETTING_UP
            bet.baseline_value = None
            bet.baseline_at = None
            bet.scout_config_id = None
        bet.save(using=WRITER_DB)
        if budget is not None and (difference := budget - totals(team_id, bet).allocated_cents):
            append(
                settings,
                bet,
                LedgerKind.ALLOCATE if difference > 0 else LedgerKind.DEALLOCATE,
                abs(difference),
                f"budget:{uuid4()}",
                user.id,
            )
        resume_spent(bet)
        return bet


def change_status(team: Team, user: User, bet_id: UUID, status: str) -> Bet:
    team_id = project_id(team)
    with transaction.atomic(using=WRITER_DB):
        settings = locked_settings(team_id)
        bet = Bet.objects.for_team(team_id).using(WRITER_DB).select_for_update().get(id=bet_id)
        if bet.status == BetStatus.CLOSED:
            raise ValidationError("This bet is closed.")
        if status == BetStatus.RUNNING:
            if bet.status != BetStatus.PAUSED:
                raise ValidationError("Only a paused bet can be resumed.")
            status = BetStatus.RUNNING if bet.baseline_at else BetStatus.SETTING_UP
        if status == BetStatus.CLOSED:
            bet.closed_at = timezone.now()
            if (available := totals(team_id, bet).available_cents) > 0:
                append(settings, bet, LedgerKind.DEALLOCATE, available, f"close:{bet.id}", user.id)
        bet.status = status
        bet.note = ""
        bet.save(using=WRITER_DB, update_fields=["status", "closed_at", "note", "updated_at"])
        if status == BetStatus.CLOSED:
            transaction.on_commit(partial(freeze, team, user, bet), using=WRITER_DB)
            transaction.on_commit(partial(finish, bet), using=WRITER_DB)
        return bet


def update_settings(team: Team, data: dict) -> BetsSettings:
    with transaction.atomic(using=WRITER_DB):
        settings = locked_settings(project_id(team))
        if data.get("budget_cents", settings.budget_cents) < totals(settings.team_id).allocated_cents:
            raise ValidationError("The project budget cannot be lower than the money already allocated.")
        if "step_models" in data:
            data = {**data, "step_models": {**settings.step_models, **data["step_models"]}}
        for key, value in data.items():
            setattr(settings, key, value)
        settings.save(using=WRITER_DB)
        return settings


def resume_spent(bet: Bet) -> None:
    if bet.status == BetStatus.SPENT and totals(bet.team_id, bet).available_cents > 0:
        bet.status = BetStatus.RUNNING
        reopen(bet)
        bet.save(using=WRITER_DB, update_fields=["status", *FROZEN_FIELDS, "updated_at"])
