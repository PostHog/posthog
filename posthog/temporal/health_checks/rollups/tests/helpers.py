import datetime as dt
from collections.abc import Iterable

from posthog.models.team import Team
from posthog.temporal.health_checks.rollups.fill import fill_day
from posthog.temporal.health_checks.rollups.framework import DailyRollup
from posthog.temporal.health_checks.rollups.freshness import RollupWindow
from posthog.temporal.health_checks.rollups.store import publish_day


def window_ending_yesterday(days: int) -> RollupWindow:
    yesterday = dt.datetime.now(dt.UTC).date() - dt.timedelta(days=1)
    return RollupWindow(start=yesterday - dt.timedelta(days=days - 1), end=yesterday)


def publish_rollup_days(rollup: type[DailyRollup], days: Iterable[dt.date]) -> None:
    """Fill each day from ClickHouse and publish it, skipping the days that have no rows."""
    live_team_ids = set(Team.objects.values_list("id", flat=True))
    for day in sorted(set(days)):
        fill = fill_day(rollup, day, live_team_ids)
        try:
            if fill.row_count:
                publish_day(rollup, fill)
        finally:
            fill.close()
