from collections.abc import Collection, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import models

from dateutil.relativedelta import relativedelta

from posthog.dataclasses import frozen
from posthog.models.events_retention_config import TeamEventsRetention
from posthog.models.team import Team
from posthog.models.team.event_retention import TeamPlan, retention_windows

PASS_INTERVAL_MONTHS = 3
CLEANUP_DAY_OF_MONTH = 3
CLEANUP_HOUR = 21
_WRITE_BATCH_SIZE = 1000


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


def reschedule_plan_deletions(
    plans: Sequence[TeamPlan],
    today: date,
    *,
    admit: Collection[int],
    previous_windows: Mapping[int, int] | None = None,
) -> dict[int, PlanDeletionState]:
    """Move each team's row to the team's window, admit the teams in `admit` that have no row, and return every row.

    Call it inside a transaction. It locks the rows before it reads the windows, so the cleanup and a settings save
    can't write back a window older than the other one saved.

    A settings save passes each team's window from before the save. The cleanup updates rows only once a month, so a
    row can still hold a window from before a plan change. Moving the row to the previous window first makes a change
    from that window get the full interval before a shorter window deletes.
    """
    team_ids = [plan.team_id for plan in plans]
    rows = {
        row.team_id: row.state
        for row in TeamEventsPlanDeletion.objects.select_for_update().filter(team_id__in=team_ids)
    }
    windows = retention_windows(plans)
    states: dict[int, PlanDeletionState] = {}
    for team_id in team_ids:
        if (state := rows.get(team_id)) is not None:
            if previous_windows is not None:
                state = with_window(state, previous_windows[team_id], today)
            states[team_id] = with_window(state, windows[team_id], today)
        elif team_id in admit:
            states[team_id] = admitted(windows[team_id], today)

    TeamEventsPlanDeletion.objects.bulk_create(
        [_row(team_id, state) for team_id, state in states.items() if team_id in rows and state != rows[team_id]],
        update_conflicts=True,
        unique_fields=["team"],
        update_fields=["months", "next_deletion_on"],
        batch_size=_WRITE_BATCH_SIZE,
    )
    # A row created after the lock was taken holds a newer window than this one, so keep it.
    TeamEventsPlanDeletion.objects.bulk_create(
        [_row(team_id, state) for team_id, state in states.items() if team_id not in rows],
        ignore_conflicts=True,
        batch_size=_WRITE_BATCH_SIZE,
    )
    return states


def _row(team_id: int, state: PlanDeletionState) -> TeamEventsPlanDeletion:
    return TeamEventsPlanDeletion(team_id=team_id, months=state.months, next_deletion_on=state.next_deletion_on)
