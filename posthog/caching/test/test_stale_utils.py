import pytest
from datetime import datetime, timedelta, UTC

from posthog.caching.utils import is_stale


# Mock Team class and stale_cache_invalidation_disabled function
class Team:
    def __init__(self, name):
        self.name = name


def stale_cache_invalidation_disabled(team):
    # Mock behavior of stale cache invalidation setting
    return False


@pytest.mark.parametrize(
    "team, date_to, interval, last_refresh, expected",
    [
        # Test cases for no interval
        (Team("A"), None, None, datetime.now(tz=UTC) - timedelta(minutes=20), True),
        (Team("A"), None, None, datetime.now(tz=UTC) - timedelta(seconds=20), False),
        (Team("A"), None, None, datetime.now(tz=UTC) - timedelta(seconds=10), False),
        # Test cases for "minute" interval
        (Team("A"), datetime.now(tz=UTC), "minute", datetime.now(tz=UTC) - timedelta(seconds=20), True),
        (Team("A"), datetime.now(tz=UTC), "minute", datetime.now(tz=UTC) - timedelta(seconds=10), False),
        # Test cases for "hour" interval
        (Team("A"), datetime.now(tz=UTC), "hour", datetime.now(tz=UTC) - timedelta(minutes=20), True),
        (Team("A"), datetime.now(tz=UTC), "hour", datetime.now(tz=UTC) - timedelta(minutes=10), False),
        # Test cases for "day" interval
        (Team("A"), None, "day", datetime.now(tz=UTC) - timedelta(hours=3), True),
        (Team("A"), datetime.now(tz=UTC), "day", datetime.now(tz=UTC) - timedelta(hours=3), True),
        (Team("A"), datetime.now(tz=UTC), "day", datetime.now(tz=UTC) - timedelta(hours=1), False),
        # Test cases for "month" interval
        (Team("A"), datetime.now(tz=UTC), "month", datetime.now(tz=UTC) - timedelta(days=2), True),
        (Team("A"), datetime.now(tz=UTC), "month", datetime.now(tz=UTC) - timedelta(hours=20), False),
        # Test case where date_to is in the past of last_refresh
        (Team("A"), datetime.now(tz=UTC) - timedelta(days=1), "day", datetime.now(tz=UTC), False),
        # Test case where stale cache invalidation is disabled
        (Team("B"), datetime.now(tz=UTC), "day", datetime.now(tz=UTC) - timedelta(hours=3), False),
        # Assuming team B has cache invalidation disabled
    ],
)
def test_is_stale(team, date_to, interval, last_refresh, expected):
    with pytest.MonkeyPatch.context() as m:
        m.setattr("posthog.caching.utils.stale_cache_invalidation_disabled", lambda t: team.name == "B")
        assert is_stale(team, date_to, interval, last_refresh) == expected
