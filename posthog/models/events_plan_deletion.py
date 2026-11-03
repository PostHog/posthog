from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import models

from dateutil.relativedelta import relativedelta

from posthog.dataclasses import frozen
from posthog.models.events_retention_config import TeamEventsRetention
from posthog.models.team import Team

PASS_INTERVAL_MONTHS = 3
CLEANUP_DAY_OF_MONTH = 3
CLEANUP_HOUR = 21
# The default window of plans with the standard data retention feature. Older plans default to their whole window.
STANDARD_DEFAULT_WINDOW_MONTHS = 24


class TeamEventsPlanDeletion(models.Model):
    """When the events cleanup next deletes a team's events past its window. Teams without a row aren't admitted."""

    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False)
    months = models.PositiveSmallIntegerField(
        help_text="The window the team's passes delete past, as of the last cleanup or settings change."
    )
    next_deletion_on = models.DateField(
        help_text="The cleanup on or after this date deletes the team's events older than the window."
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
    """Today where the cleanup schedule runs, so that a pass date shown to users is the local day its deletes start."""
    return datetime.now(ZoneInfo(cleanup_timezone())).date()


def cleanup_on_or_after(day: date) -> date:
    run_on = day.replace(day=CLEANUP_DAY_OF_MONTH)
    return run_on if run_on >= day else run_on + relativedelta(months=1)


def next_cleanup_on() -> date:
    now = datetime.now(ZoneInfo(cleanup_timezone()))
    return cleanup_on_or_after(now.date() + timedelta(days=1) if now.hour >= CLEANUP_HOUR else now.date())


def next_pass_on(today: date) -> date:
    return cleanup_on_or_after(today + relativedelta(months=PASS_INTERVAL_MONTHS))


def default_window(plan_months: int, standard: bool) -> int:
    return min(plan_months, STANDARD_DEFAULT_WINDOW_MONTHS) if standard else plan_months


def retention_window(plan_months: int, default_months: int, setting_months: int | None) -> int:
    """The window a team keeps events for: the one set in settings, never past the plan's, else the default."""
    return min(plan_months, setting_months) if setting_months is not None else default_months


def admitted(window_months: int, today: date) -> PlanDeletionState:
    return PlanDeletionState(months=window_months, next_deletion_on=next_pass_on(today))


def is_shorter_window(state: PlanDeletionState, window_months: int) -> bool:
    return window_months < state.months


def with_window(state: PlanDeletionState, window_months: int, today: date) -> PlanDeletionState:
    # A shorter window gives the organization a full interval to change it back before the extra months are deleted.
    next_deletion_on = (
        max(state.next_deletion_on, next_pass_on(today))
        if is_shorter_window(state, window_months)
        else state.next_deletion_on
    )
    return PlanDeletionState(months=window_months, next_deletion_on=next_deletion_on)


def after_pass(state: PlanDeletionState, today: date) -> PlanDeletionState:
    # A shorter window saved while the pass ran has already moved the next deletion later, so keep that date.
    return replace(state, next_deletion_on=max(state.next_deletion_on, next_pass_on(today)))


def deletion_months(setting: TeamEventsRetention | None, pass_months: int | None) -> int | None:
    """The window the cleanup deletes past for a team this run, or None to delete nothing.

    A window set in settings deletes at every monthly cleanup. The default deletes only at the team's passes.
    """
    windows = [months for months in (setting.months if setting else None, pass_months) if months is not None]
    return min(windows) if windows else None
