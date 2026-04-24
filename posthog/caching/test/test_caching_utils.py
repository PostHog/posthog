import pytest
from unittest.mock import patch

from posthog.caching.utils import IN_A_DAY, RECENTLY_ACCESSED_TEAMS_REDIS_KEY, is_team_active
from posthog.redis import get_client


@pytest.fixture(autouse=True)
def clear_redis_key():
    redis = get_client()
    redis.delete(RECENTLY_ACCESSED_TEAMS_REDIS_KEY)
    yield
    redis.delete(RECENTLY_ACCESSED_TEAMS_REDIS_KEY)


@pytest.mark.parametrize(
    "members,expected",
    [
        pytest.param({"42": 10.0}, True, id="hit"),
        # score 0 is a valid membership — guards against an `if score:` truthiness bug
        pytest.param({"42": 0}, True, id="hit_score_zero"),
        pytest.param({"99": 10.0}, False, id="miss_when_key_exists"),
    ],
)
def test_is_team_active_with_existing_key(members, expected):
    redis = get_client()
    redis.zadd(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, members)

    with patch("posthog.caching.utils.sync_execute") as mock_sync_execute:
        assert is_team_active(42) is expected
        mock_sync_execute.assert_not_called()


def test_is_team_active_populates_when_key_missing():
    with patch("posthog.caching.utils.sync_execute") as mock_sync_execute:
        mock_sync_execute.return_value = [(42, 10.0)]
        assert is_team_active(42) is True
        mock_sync_execute.assert_called_once()


def test_is_team_active_returns_false_when_clickhouse_empty():
    redis = get_client()
    with patch("posthog.caching.utils.sync_execute") as mock_sync_execute:
        mock_sync_execute.return_value = []
        assert is_team_active(42) is False
        # no populate should have happened — key still missing, no TTL set
        assert not redis.exists(RECENTLY_ACCESSED_TEAMS_REDIS_KEY)


def test_populate_sets_24h_ttl():
    redis = get_client()
    with patch("posthog.caching.utils.sync_execute") as mock_sync_execute:
        mock_sync_execute.return_value = [(42, 10.0), (43, 20.0)]
        is_team_active(42)

    ttl = redis.ttl(RECENTLY_ACCESSED_TEAMS_REDIS_KEY)
    # TTL is approximate due to the brief gap between EXPIRE and TTL calls
    assert 0 < ttl <= IN_A_DAY
    assert ttl >= IN_A_DAY - 5
