from dataclasses import replace
from datetime import date

from django.db import models

from dateutil.relativedelta import relativedelta

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.team.event_retention import DEFAULT_EVENT_RETENTION_MONTHS

PASS_INTERVAL_MONTHS = 3


class TeamEventsPlanDeletion(models.Model):
    """When the events cleanup next deletes a team's events past its plan's window. Teams without a row aren't admitted."""

    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False)
    months = models.PositiveSmallIntegerField(help_text="The plan's events retention window at the last cleanup.")
    next_deletion_on = models.DateField(
        help_text="The cleanup on or after this date deletes the team's events older than the plan's window."
    )

    @property
    def state(self) -> "PlanDeletionState":
        return PlanDeletionState(months=self.months, next_deletion_on=self.next_deletion_on)


@frozen
class PlanDeletionState:
    months: int
    next_deletion_on: date


def _next_pass(today: date) -> date:
    return today + relativedelta(months=PASS_INTERVAL_MONTHS)


def admitted(plan_months: int, today: date) -> PlanDeletionState:
    return PlanDeletionState(months=plan_months, next_deletion_on=_next_pass(today))


def is_downgrade(state: PlanDeletionState, plan_months: int) -> bool:
    return plan_months < state.months


def with_plan(state: PlanDeletionState, plan_months: int, today: date) -> PlanDeletionState:
    # A shorter window gives the organization a full interval to upgrade before the extra months are deleted.
    next_deletion_on = (
        max(state.next_deletion_on, _next_pass(today)) if is_downgrade(state, plan_months) else state.next_deletion_on
    )
    return PlanDeletionState(months=plan_months, next_deletion_on=next_deletion_on)


def after_pass(state: PlanDeletionState, today: date) -> PlanDeletionState:
    return replace(state, next_deletion_on=_next_pass(today))


def deletion_months(setting_months: int | None, plan_months: int | None, pass_due: bool) -> int | None:
    """The retention window the cleanup deletes past for a team this run, or None to delete nothing."""
    windows = [setting_months]
    if pass_due and plan_months is not None and plan_months < DEFAULT_EVENT_RETENTION_MONTHS:
        windows.append(plan_months)
    set_windows = [months for months in windows if months is not None]
    return min(set_windows) if set_windows else None
