import pytest
from unittest.mock import patch

from posthog.caching.utils import (
    IN_A_DAY,
    IN_AN_HOUR,
    RECENTLY_ACCESSED_TEAMS_POPULATED_KEY,
    RECENTLY_ACCESSED_TEAMS_REDIS_KEY,
    active_teams,
    is_team_active,
)
from posthog.redis import get_client


@pytest.fixture(autouse=True)
def clear_redis_keys():
    redis = get_client()
    redis.delete(RECENTLY_ACCESSED_TEAMS_REDIS_KEY)
    redis.delete(RECENTLY_ACCESSED_TEAMS_POPULATED_KEY)
    yield
    redis.delete(RECENTLY_ACCESSED_TEAMS_REDIS_KEY)
    redis.delete(RECENTLY_ACCESSED_TEAMS_POPULATED_KEY)


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
    redis.set(RECENTLY_ACCESSED_TEAMS_POPULATED_KEY, "1")

    with patch("posthog.caching.utils.sync_execute") as mock_sync_execute:
        assert is_team_active(42) is expected
        mock_sync_execute.assert_not_called()


def test_is_team_active_populates_when_key_missing():
    with patch("posthog.caching.utils.sync_execute") as mock_sync_execute:
        mock_sync_execute.return_value = [(42, 10.0)]
        assert is_team_active(42) is True
        mock_sync_execute.assert_called_once()


def test_is_team_active_returns_false_when_clickhouse_empty():
    with patch("posthog.caching.utils.sync_execute") as mock_sync_execute:
        mock_sync_execute.return_value = []
        assert is_team_active(42) is False
        mock_sync_execute.assert_called_once()


def test_is_team_active_caches_empty_clickhouse_result():
    redis = get_client()
    with patch("posthog.caching.utils.sync_execute") as mock_sync_execute:
        mock_sync_execute.return_value = []

        assert is_team_active(42) is False
        assert is_team_active(43) is False
        assert is_team_active(44) is False

        assert mock_sync_execute.call_count == 1
        assert redis.exists(RECENTLY_ACCESSED_TEAMS_POPULATED_KEY)


def test_active_teams_caches_empty_clickhouse_result():
    redis = get_client()
    with patch("posthog.caching.utils.sync_execute") as mock_sync_execute:
        mock_sync_execute.return_value = []

        assert active_teams() == set()
        assert active_teams() == set()

        assert mock_sync_execute.call_count == 1
        assert redis.exists(RECENTLY_ACCESSED_TEAMS_POPULATED_KEY)


def test_populate_sets_24h_ttl_on_both_keys():
    redis = get_client()
    with patch("posthog.caching.utils.sync_execute") as mock_sync_execute:
        mock_sync_execute.return_value = [(42, 10.0), (43, 20.0)]
        is_team_active(42)

    for key in (RECENTLY_ACCESSED_TEAMS_REDIS_KEY, RECENTLY_ACCESSED_TEAMS_POPULATED_KEY):
        ttl = redis.ttl(key)
        # TTL is approximate due to the brief gap between EXPIRE and TTL calls
        assert 0 < ttl <= IN_A_DAY, f"{key} ttl={ttl}"
        assert ttl >= IN_A_DAY - 5, f"{key} ttl={ttl}"


def test_populate_clears_stale_zset_when_clickhouse_empty():
    redis = get_client()
    redis.zadd(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, {"42": 10.0})

    with patch("posthog.caching.utils.sync_execute") as mock_sync_execute:
        mock_sync_execute.return_value = []
        assert is_team_active(99) is False

    assert not redis.exists(RECENTLY_ACCESSED_TEAMS_REDIS_KEY)
    with patch("posthog.caching.utils.sync_execute") as mock_sync_execute:
        assert is_team_active(42) is False
        mock_sync_execute.assert_not_called()


def test_populate_sets_short_ttl_on_marker_when_clickhouse_empty():
    redis = get_client()
    with patch("posthog.caching.utils.sync_execute") as mock_sync_execute:
        mock_sync_execute.return_value = []
        is_team_active(42)

    ttl = redis.ttl(RECENTLY_ACCESSED_TEAMS_POPULATED_KEY)
    assert 0 < ttl <= IN_AN_HOUR
    assert ttl >= IN_AN_HOUR - 5
