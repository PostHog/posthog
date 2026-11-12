from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import models, transaction

from dateutil.relativedelta import relativedelta

from posthog.cloud_utils import is_cloud
from posthog.dataclasses import frozen
from posthog.models.events_retention_config import (
    TeamEventsRetention,
    effective_events_retention,
    lock_organization_retention,
)
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.team.event_retention import (
    TeamPlan,
    organization_events_retention_months,
    reconcile_organization_events_retention,
    retention_periods,
    should_delete_past_default_period,
    team_plan,
)
from posthog.ph_client import ph_scoped_capture
from posthog.utils import get_instance_region

PASS_INTERVAL_MONTHS = 3
CLEANUP_DAY_OF_MONTH = 3
CLEANUP_HOUR = 21
DELETION_NOTICE_DAYS = 14
RETENTION_SHORTENED_EVENT = "events retention period shortened"
DELETION_UPCOMING_EVENT = "events retention deletion upcoming"
_WRITE_BATCH_SIZE = 1000


class TeamEventsPlanDeletion(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False)
    months = models.PositiveSmallIntegerField(
        help_text="The period the team's passes delete past, as of the last cleanup or settings change."
    )
    next_deletion_on = models.DateField(
        help_text="The cleanup on or after this date deletes the team's events older than the period."
    )

    @property
    def state(self) -> "PlanDeletionState":
        return PlanDeletionState(months=self.months, next_deletion_on=self.next_deletion_on)


@frozen
class PlanDeletionState:
    months: int
    next_deletion_on: date


def cleanup_timezone() -> str:
    return "Europe/Paris" if settings.CLOUD_DEPLOYMENT == "EU" else "America/Los_Angeles"


def cleanup_date() -> date:
    return datetime.now(ZoneInfo(cleanup_timezone())).date()


def cleanup_on_or_after(day: date) -> date:
    run_on = day.replace(day=CLEANUP_DAY_OF_MONTH)
    return run_on if run_on >= day else run_on + relativedelta(months=1)


def next_cleanup_on() -> date:
    now = datetime.now(ZoneInfo(cleanup_timezone()))
    return cleanup_on_or_after(now.date() + timedelta(days=1) if now.hour >= CLEANUP_HOUR else now.date())


def next_pass_on(today: date) -> date:
    return cleanup_on_or_after(today + relativedelta(months=PASS_INTERVAL_MONTHS))


def admitted(period_months: int, today: date) -> PlanDeletionState:
    return PlanDeletionState(months=period_months, next_deletion_on=next_pass_on(today))


def is_shorter_period(state: PlanDeletionState, period_months: int) -> bool:
    return period_months < state.months


def with_period(state: PlanDeletionState, period_months: int, today: date) -> PlanDeletionState:
    next_deletion_on = (
        max(state.next_deletion_on, next_pass_on(today))
        if is_shorter_period(state, period_months)
        else state.next_deletion_on
    )
    return PlanDeletionState(months=period_months, next_deletion_on=next_deletion_on)


def after_pass(state: PlanDeletionState, today: date) -> PlanDeletionState:
    return replace(state, next_deletion_on=max(state.next_deletion_on, next_pass_on(today)))


def deletion_months(setting: TeamEventsRetention | None, due_pass_months: int | None) -> int | None:
    periods = [months for months in (setting.months if setting else None, due_pass_months) if months is not None]
    return min(periods) if periods else None


def deleting_plans(teams: Iterable[Team]) -> list[TeamPlan]:
    return [team_plan(team) for team in teams if should_delete_past_default_period(team)]


def reschedule_plan_deletions(plans: Sequence[TeamPlan], today: date) -> dict[int, PlanDeletionState]:
    team_ids = [plan.team_id for plan in plans]
    rows = {
        row.team_id: row.state
        for row in TeamEventsPlanDeletion.objects.select_for_update().filter(team_id__in=team_ids)
    }
    periods = retention_periods(plans)
    states: dict[int, PlanDeletionState] = {}
    for team_id in team_ids:
        state = rows.get(team_id)
        states[team_id] = (
            with_period(state, periods[team_id], today) if state is not None else admitted(periods[team_id], today)
        )

    TeamEventsPlanDeletion.objects.bulk_create(
        [_row(team_id, state) for team_id, state in states.items() if team_id in rows and state != rows[team_id]],
        update_conflicts=True,
        unique_fields=["team"],
        update_fields=["months", "next_deletion_on"],
        batch_size=_WRITE_BATCH_SIZE,
    )
    TeamEventsPlanDeletion.objects.bulk_create(
        [_row(team_id, state) for team_id, state in states.items() if team_id not in rows],
        ignore_conflicts=True,
        batch_size=_WRITE_BATCH_SIZE,
    )
    return states


def _row(team_id: int, state: PlanDeletionState) -> TeamEventsPlanDeletion:
    return TeamEventsPlanDeletion(team_id=team_id, months=state.months, next_deletion_on=state.next_deletion_on)


def apply_events_retention_change(
    organization: Organization, previous_months: int | None, previous_standard_retention: bool
) -> None:
    """Align the organization's teams and their passes with its plan period. When a downgrade shortens the period of
    any team, push those teams' passes and tell the admins.

    The first billing sync has no previous period. It moves teams off the 84-month fallback, which is no downgrade.
    """
    from posthog.tasks.tasks import report_events_retention_shortened

    with transaction.atomic():
        lock_organization_retention(organization.id)
        if not reconcile_organization_events_retention(organization) or previous_months is None:
            return
        teams = list(Team.objects.filter(organization_id=organization.id))
        if organization_events_retention_months(organization) >= previous_months:
            reschedule_plan_deletions(deleting_plans(teams), cleanup_date())
            return
        shortened = _shortened_teams(organization.id, teams, previous_months, previous_standard_retention)
        if not shortened:
            return
        states = reschedule_plan_deletions(deleting_plans(shortened), cleanup_date())
    deletion_on = min((state.next_deletion_on for state in states.values()), default=None)
    notice = {**_notice(organization, deletion_on), "previous_retention_months": previous_months}
    report_events_retention_shortened.delay(str(organization.id), notice)


def _shortened_teams(
    organization_id: UUID, teams: Sequence[Team], previous_months: int, previous_standard_retention: bool
) -> list[Team]:
    plans = [team_plan(team) for team in teams]
    before = retention_periods(
        [replace(plan, plan_months=previous_months) for plan in plans],
        {organization_id} if previous_standard_retention else set(),
    )
    after = retention_periods(plans)
    return [team for team in teams if after[team.id] < before[team.id]]


def report_retention_shortened(organization_id: UUID, notice: dict[str, object]) -> None:
    _notify_admins(RETENTION_SHORTENED_EVENT, {organization_id: notice})


def report_upcoming_deletions() -> int:
    """Tell the admins of each organization with a pass at the next cleanup, exactly 14 days before it.

    Only that one day sends, so each pass gets one event without a record of what was sent. A team whose set period is
    at or below its pass's period is left out, because the monthly cleanup already deletes everything that pass would.
    """
    deletion_on = next_cleanup_on()
    if deletion_on - cleanup_date() != timedelta(days=DELETION_NOTICE_DAYS):
        return 0
    due = TeamEventsPlanDeletion.objects.filter(next_deletion_on__lte=deletion_on).values("team_id")
    teams = Team.objects.filter(id__in=due).only("id", "organization_id", "event_retention_months")
    plans = deleting_plans(teams)
    with transaction.atomic():
        states = reschedule_plan_deletions(plans, cleanup_date())
    deleted_monthly = {
        setting.team_id
        for setting in effective_events_retention(team_ids=[plan.team_id for plan in plans])
        if setting.months <= states[setting.team_id].months
    }
    organization_ids = {
        plan.organization_id
        for plan in plans
        if plan.team_id not in deleted_monthly and states[plan.team_id].next_deletion_on <= deletion_on
    }
    for organization in Organization.objects.filter(id__in=organization_ids).only(
        "id", "name", "available_product_features"
    ):
        _notify_admins(DELETION_UPCOMING_EVENT, {organization.id: _notice(organization, deletion_on)})
    return len(organization_ids)


def _notice(organization: Organization, deletion_on: date | None) -> dict[str, object]:
    return {
        "organization_name": organization.name,
        "retention_months": organization_events_retention_months(organization),
        "deletion_scheduled_on": deletion_on.isoformat() if deletion_on else None,
    }


def _notify_admins(event: str, notices: dict[UUID, dict[str, object]]) -> None:
    if not is_cloud() or not notices:
        return
    admins = OrganizationMembership.objects.filter(
        organization_id__in=notices, level__gte=OrganizationMembership.Level.ADMIN, user__is_active=True
    ).values_list("organization_id", "user__distinct_id")
    with ph_scoped_capture(raise_on_error=True, event_region=get_instance_region()) as capture:
        for organization_id, distinct_id in admins:
            capture(
                distinct_id=distinct_id,
                event=event,
                properties={**notices[organization_id], "$update_person_last_seen_at": False},
                groups={"organization": str(organization_id)},
            )
