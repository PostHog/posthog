import pytest
from datetime import datetime, timedelta, UTC
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
        (team_a, None, None, timedelta(minutes=20), True),
        (team_a, None, None, timedelta(seconds=20), False),
        (team_a, None, None, timedelta(seconds=10), False),
        # Test cases for "minute" interval
        (team_a, None, "minute", timedelta(seconds=20), True),
        (team_a, None, "minute", timedelta(seconds=10), False),
        # Test cases for "hour" interval
        (team_a, date_to, "hour", timedelta(minutes=20), True),
        (team_a, date_to, "hour", timedelta(minutes=10), False),
        # Test cases for "day" interval
        (team_a, None, "day", timedelta(hours=3), True),
        (team_a, date_to, "day", timedelta(hours=3), True),
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
