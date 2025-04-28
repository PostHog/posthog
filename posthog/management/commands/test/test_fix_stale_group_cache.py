import pytest
from unittest.mock import patch
from django.core.management import call_command, CommandError


@pytest.fixture
def fake_redis():
    # Simulate a Redis client with scan, object, ttl, and expire
    class FakeRedis:
        def __init__(self):
            self.reset()

        def reset(self):
            self.keys = {
                "group_data_cache_v2:1": {"idletime": 8000000, "ttl": -1},
                "group_data_cache_v2:2": {"idletime": 100, "ttl": -1},
                "group_data_cache_v2:3": {"idletime": 8000000, "ttl": 100},
            }
            self.expired = {}

        def scan(self, cursor=0, match=None, count=None):
            # Return all keys at once for simplicity
            return 0, list(self.keys.keys())

        def pipeline(self):
            return self

        def object(self, what, key):
            self._last_key = key
            return self

        def ttl(self, key):
            return self

        def execute(self):
            # Return idletime and ttl for each key in order
            results = []
            for key in self.keys:
                results.append(self.keys[key]["idletime"])
                results.append(self.keys[key]["ttl"])
            return results

        def expire(self, key, ttl):
            self.expired[key] = ttl

        def connection_pool(self):
            return "connection_pool"

    return FakeRedis()


@patch("posthog.management.commands.fix_stale_group_cache.get_client")
def test_dry_run_sets_no_ttl(mock_get_client, fake_redis):
    mock_get_client.return_value = fake_redis
    call_command("fix_stale_group_cache", "--dry-run", "--idle-threshold-days=1")
    # Should not set any TTLs in dry run
    assert fake_redis.expired == {}


@patch("posthog.management.commands.fix_stale_group_cache.get_client")
def test_default_is_dry_run(mock_get_client, fake_redis):
    mock_get_client.return_value = fake_redis
    call_command("fix_stale_group_cache", "--idle-threshold-days=1")
    # Should not set any TTLs in dry run
    assert fake_redis.expired == {}


@patch("posthog.management.commands.fix_stale_group_cache.get_client")
def test_real_run_sets_ttl(mock_get_client, fake_redis):
    mock_get_client.return_value = fake_redis
    call_command(
        "fix_stale_group_cache", "--idle-threshold-days=1", "--min-ttl-days=1", "--max-ttl-days=1", "--no-dry-run"
    )
    # Only keys with idletime > threshold and ttl == -1 get expired
    assert "group_data_cache_v2:1" in fake_redis.expired
    # group_data_cache_v2:2 is not idle enough, group_data_cache_v2:3 already has TTL


@patch("posthog.management.commands.fix_stale_group_cache.get_client")
def test_min_ttl_greater_than_max_raises(mock_get_client, fake_redis):
    mock_get_client.return_value = fake_redis
    with pytest.raises(CommandError):
        call_command("fix_stale_group_cache", "--min-ttl-days=5", "--max-ttl-days=1", "--no-dry-run")


@patch("posthog.management.commands.fix_stale_group_cache.get_client")
def test_idle_threshold_respected(mock_get_client, fake_redis):
    mock_get_client.return_value = fake_redis
    call_command("fix_stale_group_cache", "--idle-threshold-days=100000", "--no-dry-run")
    # No keys should be expired, as none are idle enough
    assert fake_redis.expired == {}


# ... existing code ...


@patch("posthog.management.commands.fix_stale_group_cache.get_client")
def test_ttl_randomization_varies_and_within_bounds(mock_get_client, fake_redis):
    mock_get_client.return_value = fake_redis
    min_days = 2
    max_days = 5

    # Call 1
    call_command(
        "fix_stale_group_cache",
        "--idle-threshold-days=1",
        f"--min-ttl-days={min_days}",
        f"--max-ttl-days={max_days}",
        "--no-dry-run",
    )
    ttls_1 = list(fake_redis.expired.values())

    # Reset expired and call again
    fake_redis.reset()
    call_command(
        "fix_stale_group_cache",
        "--idle-threshold-days=1",
        f"--min-ttl-days={min_days}",
        f"--max-ttl-days={max_days}",
        "--no-dry-run",
    )
    ttls_2 = list(fake_redis.expired.values())

    # Should have at least one TTL set each time
    assert ttls_1 and ttls_2

    # Check all TTLs are within bounds (in seconds)
    for ttl in ttls_1 + ttls_2:
        days = ttl // (24 * 3600)
        assert min_days <= days <= max_days, f"TTL {ttl} not in range {min_days}-{max_days}"

    # Check that at least one TTL differs between runs (randomization)
    assert set(ttls_1) != set(ttls_2), f"TTLs did not vary: {ttls_1} vs {ttls_2}"
