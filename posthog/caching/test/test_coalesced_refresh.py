import uuid

import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from django_redis.cache import RedisCache
from redis.exceptions import RedisError

from posthog.caching.coalesced_refresh import CacheRefreshInProgress, CoalescedCacheRefresh


def refresh_cache(key: str, fetch, *, stale=True) -> CoalescedCacheRefresh[dict]:
    return CoalescedCacheRefresh(
        key,
        timeout=120,
        is_stale=lambda value: value is None or stale,
        is_valid=lambda value: isinstance(value, dict),
        refresh=fetch,
    )


class TestCoalescedCacheRefresh(SimpleTestCase):
    def test_publish_uses_owner_check_and_encoded_snapshot(self):
        key = f"coalesced:test:{uuid.uuid4().hex}"
        backend = MagicMock(spec=RedisCache)
        backend.make_key.side_effect = lambda value: f"posthog:1:{value}"
        backend.client.encode.return_value = b"encoded"
        redis = MagicMock()
        redis.eval.side_effect = [1, 0]
        with (
            patch("posthog.caching.coalesced_refresh.caches", {"default": backend}),
            patch("posthog.caching.coalesced_refresh.get_redis_connection", return_value=redis),
        ):
            refresh = refresh_cache(key, lambda _renew: {"version": 1})
            assert refresh._publish({"version": 1}, "first")
            assert not refresh._publish({"version": 0}, "first")
        script, count, claim_key, snapshot_key, owner, encoded, ttl = redis.eval.call_args_list[0].args
        assert "redis.call('get', KEYS[1]) ~= ARGV[1]" in script
        assert (count, claim_key, snapshot_key, owner, encoded, ttl) == (
            2,
            f"posthog:1:{key}:refresh",
            f"posthog:1:{key}",
            "first",
            b"encoded",
            120_000,
        )

    def test_stale_follower_returns_snapshot_without_fetch(self):
        key = f"coalesced:test:{uuid.uuid4().hex}"
        cache.set(key, {"version": 1})
        fetch = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = False
        refresh = refresh_cache(key, fetch)
        with patch.object(refresh, "_lock", return_value=lock):
            assert refresh.get() == {"version": 1}
        fetch.assert_not_called()

    def test_cold_follower_waits_then_raises(self):
        refresh = refresh_cache(f"coalesced:test:{uuid.uuid4().hex}", MagicMock())
        lock = MagicMock()
        lock.acquire.return_value = False
        with patch.object(refresh, "_lock", return_value=lock):
            with pytest.raises(CacheRefreshInProgress):
                refresh.get()
        assert lock.acquire.call_count == 2

    def test_owner_rechecks_snapshot_after_claim(self):
        key = f"coalesced:test:{uuid.uuid4().hex}"
        cache.set(key, {"version": 2})
        fetch = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = True
        refresh = refresh_cache(key, fetch, stale=False)
        with (
            patch.object(refresh, "read", side_effect=[None, {"version": 2}]),
            patch.object(refresh, "_lock", return_value=lock),
        ):
            assert refresh.get() == {"version": 2}
        fetch.assert_not_called()
        lock.release.assert_called_once()

    def test_lost_claim_stops_refresh_and_returns_stale_value(self):
        key = f"coalesced:test:{uuid.uuid4().hex}"
        cache.set(key, {"version": 1})
        lock = MagicMock()
        lock.acquire.return_value = True
        lock.reacquire.return_value = False

        def fetch(renew):
            if not renew():
                raise ValueError("claim expired")
            return {"version": 2}

        refresh = refresh_cache(key, fetch)
        with patch.object(refresh, "_lock", return_value=lock):
            assert refresh.get() == {"version": 1}
        assert cache.get(f"{key}:refresh_failed") is True

    def test_redis_renewal_error_does_not_discard_fetched_value(self):
        key = f"coalesced:test:{uuid.uuid4().hex}"
        lock = MagicMock()
        lock.acquire.return_value = True
        lock.reacquire.side_effect = RedisError("unavailable")
        fetch = MagicMock(side_effect=lambda renew: {"version": 2} if renew() else None)
        refresh = refresh_cache(key, fetch)
        with patch.object(refresh, "_lock", return_value=lock), patch.object(refresh, "_publish", return_value=False):
            assert refresh.get() == {"version": 2}

    def test_failed_refresh_backs_off_while_serving_stale_value(self):
        key = f"coalesced:test:{uuid.uuid4().hex}"
        cache.set(key, {"version": 1})
        fetch = MagicMock(side_effect=ValueError("upstream failed"))
        lock = MagicMock()
        lock.acquire.return_value = True
        refresh = refresh_cache(key, fetch)
        with patch.object(refresh, "_lock", return_value=lock):
            assert refresh.get() == {"version": 1}
            assert refresh.get() == {"version": 1}
        fetch.assert_called_once()
