from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from posthog.caching.utils import is_stale


# Mock Team class and stale_cache_invalidation_disabled function
class Team:
    def __init__(self, name):
        self.name = name


def stale_cache_invalidation_disabled(team):
    # Mock behavior of stale cache invalidation setting
    return False


team_a = Team("A")
team_b = Team("B")

date_to = datetime(2021, 1, 1, 0, 0, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "team, date_to, interval, last_refresh, expected",
    [
        # Test cases for no interval
        (team_a, None, None, timedelta(hours=7), True),
        (team_a, None, None, timedelta(seconds=20), False),
        (team_a, None, None, timedelta(seconds=10), False),
        # Test cases for "minute" interval
        (team_a, None, "minute", timedelta(minutes=6), True),
        (team_a, None, "minute", timedelta(seconds=10), False),
        # Test cases for "hour" interval
        (team_a, date_to, "hour", timedelta(hours=1, minutes=1), True),
        (team_a, date_to, "hour", timedelta(minutes=10), False),
        # Test cases for "day" interval
        (team_a, None, "day", timedelta(hours=7), True),
        (team_a, date_to, "day", timedelta(hours=7), True),
        (team_a, date_to, "day", timedelta(hours=1), False),
        # Test cases for "month" interval
        (team_a, date_to, "month", timedelta(days=2), True),
        (team_a, date_to, "month", timedelta(hours=20), False),
        # Test case where date_to is in the past of last_refresh
        (team_a, date_to - timedelta(days=1), "day", timedelta(seconds=0), False),
        # Test case where stale cache invalidation is disabled
        (team_b, date_to, "day", timedelta(hours=3), False),
        # Assuming team B has cache invalidation disabled
    ],
)
@freeze_time("2021-01-01T00:00:00Z")
def test_is_stale(team, date_to, interval, last_refresh, expected):
    with pytest.MonkeyPatch.context() as m:
        m.setattr("posthog.caching.utils.stale_cache_invalidation_disabled", lambda t: team.name == "B")
        assert is_stale(team, date_to, interval, datetime.now(UTC) - last_refresh) == expected


@pytest.mark.parametrize(
    "team, date_to, interval, last_refresh, target_age, expected",
    [
        # target_age in the future -> not stale (even though minute interval would make it stale)
        (
            team_a,
            None,
            "minute",
            datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
            datetime(2025, 1, 1, 1, 0, 0, tzinfo=UTC),
            False,
        ),
        # target_age in the past -> stale (even though day interval would keep it fresh)
        (
            team_a,
            None,
            "day",
            datetime(2024, 12, 31, 22, 0, 0, tzinfo=UTC),
            datetime(2024, 12, 31, 23, 0, 0, tzinfo=UTC),
            True,
        ),
        # target_age exactly at current time -> not stale (boundary case)
        (
            team_a,
            None,
            "hour",
            datetime(2024, 12, 31, 23, 0, 0, tzinfo=UTC),
            datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
            False,
        ),
    ],
)
@freeze_time("2025-01-01T00:00:00Z")
def test_is_stale_with_target_age(team, date_to, interval, last_refresh, target_age, expected):
    """Test that target_age parameter overrides interval-based staleness calculation."""
    with pytest.MonkeyPatch.context() as m:
        m.setattr("posthog.caching.utils.stale_cache_invalidation_disabled", lambda t: False)
        assert is_stale(team, date_to, interval, last_refresh, target_age=target_age) == expected
