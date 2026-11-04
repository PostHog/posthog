from collections.abc import Collection, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import models

from dateutil.relativedelta import relativedelta

from posthog.dataclasses import frozen
from posthog.models.events_retention_config import TeamEventsRetention
from posthog.models.team import Team
from posthog.models.team.event_retention import TeamPlan, retention_periods

PASS_INTERVAL_MONTHS = 3
CLEANUP_DAY_OF_MONTH = 3
CLEANUP_HOUR = 21
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


def reschedule_plan_deletions(
    plans: Sequence[TeamPlan], today: date, *, admit: Collection[int]
) -> dict[int, PlanDeletionState]:
    team_ids = [plan.team_id for plan in plans]
    rows = {
        row.team_id: row.state
        for row in TeamEventsPlanDeletion.objects.select_for_update().filter(team_id__in=team_ids)
    }
    periods = retention_periods(plans)
    states: dict[int, PlanDeletionState] = {}
    for team_id in team_ids:
        if (state := rows.get(team_id)) is not None:
            states[team_id] = with_period(state, periods[team_id], today)
        elif team_id in admit:
            states[team_id] = admitted(periods[team_id], today)

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
