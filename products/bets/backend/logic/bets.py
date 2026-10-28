from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from ..db import WRITER_DB
from ..facade.enums import BetStatus, LedgerKind, WorkStage
from ..models import Bet, BetsSettings, LedgerEntry, WorkItem
from .ledger import append, totals
from .loop import add_owner_idea, end_experiment, finish
from .metrics import validate_goal
from .workspace import get_settings, project_id

if TYPE_CHECKING:
    from posthog.models import Team, User

GOAL_FIELDS = frozenset(
    {"goal_insight", "goal_description", "goal_metric", "target", "direction", "secondary_metrics", "repositories"}
)
OPEN = (WorkStage.WORKING, WorkStage.REVIEW, WorkStage.LIVE)


def validate_insights(team: Team, user: User, data: dict) -> None:
    if data.get("goal_insight"):
        validate_goal(team, user, data["goal_insight"])
    for secondary in data.get("secondary_metrics", []):
        validate_goal(team, user, secondary["insight"])


def create_bet(team: Team, user: User, data: dict) -> Bet:
    team_id = project_id(team)
    validate_insights(team, user, data)
    payload = dict(data)
    budget = payload.pop("budget_cents")
    operation_id = payload.pop("operation_id")
    ideas = [idea for idea in payload.pop("ideas", None) or [] if idea.strip()]
    with transaction.atomic(using=WRITER_DB):
        settings = (
            BetsSettings.objects.for_team(team_id).using(WRITER_DB).select_for_update().get(id=get_settings(team_id).id)
        )
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
    with transaction.atomic(using=WRITER_DB):
        settings = (
            BetsSettings.objects.for_team(team_id).using(WRITER_DB).select_for_update().get(id=get_settings(team_id).id)
        )
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
        goal_changed = any(
            key in payload and payload[key] != getattr(bet, key)
            for key in GOAL_FIELDS
            if not (first_target and key in ("target", "goal_metric", "direction"))
        )
        for field, value in payload.items():
            setattr(bet, field, value)
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
        settings = (
            BetsSettings.objects.for_team(team_id).using(WRITER_DB).select_for_update().get(id=get_settings(team_id).id)
        )
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
            transaction.on_commit(partial(finish, bet), using=WRITER_DB)
        return bet


def update_settings(team: Team, data: dict) -> BetsSettings:
    with transaction.atomic(using=WRITER_DB):
        settings = (
            BetsSettings.objects.for_team(project_id(team))
            .using(WRITER_DB)
            .select_for_update()
            .get(id=get_settings(project_id(team)).id)
        )
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
        bet.save(using=WRITER_DB, update_fields=["status", "updated_at"])
