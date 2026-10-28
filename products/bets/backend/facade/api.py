from uuid import UUID

from django.db import transaction
from django.shortcuts import get_object_or_404

from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.ingress.contracts import WebhookDelivery
from posthog.models import Integration, Team, User

from ..db import WRITER_DB
from ..facade.contracts import Metric
from ..logic import access, bets, loop, read
from ..logic.activity import ActivityEntry, recent_activity
from ..logic.metrics import metric, refresh_metrics, validate_goal
from ..logic.spend import bet_for_run
from ..logic.stages import LIVE
from ..logic.state import takes_ideas
from ..logic.usage import track
from ..logic.workspace import get_settings, project_id
from ..models import Bet


def wake(bet: Bet) -> None:
    from ..tasks.tasks import coordinate_bet  # noqa: PLC0415 - avoid loading Celery on product facade imports

    if bet.status in LIVE:
        transaction.on_commit(lambda: coordinate_bet.delay(bet.team_id, str(bet.id)), using=WRITER_DB, robust=True)


def authorize(team: Team, user: User, *, write: bool) -> None:
    access.require(team, user, write=write)
    if team.parent_team is not None:
        access.require(team.parent_team, user, write=write)
    if not access.bets_enabled(team):
        raise PermissionDenied("Bets is not enabled for this project.")


def _bet(team: Team, bet_id: str | UUID) -> Bet:
    return get_object_or_404(Bet.objects.for_team(project_id(team)).using(WRITER_DB), id=bet_id)


def overview(team: Team, user: User) -> dict:
    return read.overview(team, user)


def metric_preview(team: Team, user: User, short_id: str) -> Metric:
    validate_goal(team, user, short_id)
    refresh_metrics(team, user, [short_id])
    return metric(team, user, short_id, complete=True)


def detail(team: Team, user: User, bet_id: str | UUID) -> dict:
    return read.detail(team, user, _bet(team, bet_id))


def activity(team: Team, user: User, bet_id: str | UUID) -> list[ActivityEntry]:
    return recent_activity(team.parent_team or team, user, _bet(team, bet_id))


def create(team: Team, user: User, data: dict) -> dict:
    bet = bets.create_bet(team, user, data)
    track(
        team,
        user,
        "bet created",
        {"bet_id": str(bet.id), "guardrails": len(bet.secondary_metrics), "has_insight": bool(bet.goal_insight)},
    )
    wake(bet)
    return read.detail(team, user, bet)


def update(team: Team, user: User, bet_id: str | UUID, data: dict) -> dict:
    bet = _bet(team, bet_id)
    access.require_owner(team, user, bet.owner_id)
    updated = bets.update_bet(team, user, bet.id, data)
    track(
        team,
        user,
        "bet updated",
        {"bet_id": str(bet.id), "fields": sorted(data), "goal_changed": updated.goal_version != bet.goal_version},
    )
    wake(updated)
    return read.detail(team, user, updated)


def change_status(team: Team, user: User, bet_id: str | UUID, status: str) -> dict:
    bet = _bet(team, bet_id)
    access.require_owner(team, user, bet.owner_id)
    changed = bets.change_status(team, user, bet.id, status)
    track(team, user, "bet status changed", {"bet_id": str(bet.id), "from": bet.status, "to": changed.status})
    if changed.status not in LIVE:
        loop.set_scout(changed, False)
    wake(changed)
    return read.detail(team, user, changed)


def work(
    team: Team, user: User, bet_id: str | UUID, work_id: UUID, action: str, reason: str = "", plan: dict | None = None
) -> dict:
    bet = _bet(team, bet_id)
    access.require_owner(team, user, bet.owner_id)
    loop.act(bet, work_id, action, user=user, reason=reason, plan=plan)
    track(
        team,
        user,
        "bet work action",
        {
            "bet_id": str(bet.id),
            "work_id": str(work_id),
            "action": action,
            "plan_days": plan.get("days") if plan else None,
            "plan_mde": plan.get("mde") if plan else None,
        },
    )
    wake(bet)
    return read.detail(team, user, _bet(team, bet_id))


def add_idea(team: Team, user: User, bet_id: str | UUID, title: str) -> dict:
    bet = _bet(team, bet_id)
    access.require_owner(team, user, bet.owner_id)
    if not takes_ideas(bet):
        raise ValidationError("This bet does not take new ideas.")
    loop.add_owner_idea(bet, title)
    track(team, user, "bet owner idea added", {"bet_id": str(bet.id)})
    wake(bet)
    return read.detail(team, user, _bet(team, bet_id))


def settings(team: Team, user: User) -> dict:
    return read.settings_entry(get_settings(project_id(team)), user)


def update_settings(team: Team, user: User, data: dict) -> dict:
    access.require_manager(team, user)
    if data.get("north_star_insight"):
        validate_goal(team, user, data["north_star_insight"])
    updated = bets.update_settings(team, data)
    track(team, user, "bets settings updated", {"fields": sorted(data)})
    return read.settings_entry(updated, user)


def accept_github_delivery(delivery: WebhookDelivery) -> None:
    installation = delivery.payload.get("installation", {})
    repository = delivery.payload.get("repository", {})
    if not isinstance(installation, dict) or not isinstance(repository, dict) or not installation.get("id"):
        return
    name = repository.get("full_name")
    if not isinstance(name, str):
        return
    team_ids = (
        Integration.objects.filter(kind="github")
        .for_github_installation_id(installation["id"])
        .values_list("team_id", flat=True)
    )
    for bet in (
        Bet.objects.unscoped()
        .using(WRITER_DB)
        .filter(team_id__in=list(team_ids), repository__iexact=name, status__in=LIVE)
    ):
        wake(bet)


def reconcile_run(team_id: int, run_id: UUID) -> None:
    if bet := bet_for_run(team_id, run_id):
        wake(bet)
