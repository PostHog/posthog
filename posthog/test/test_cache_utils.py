import threading
from datetime import timedelta
from time import sleep, time
from typing import Optional

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

import redis.exceptions

from posthog.cache_utils import cache_for

mocked_dependency = Mock()
mocked_dependency.return_value = 1

order_of_events = Mock(side_effect=lambda x: print(x))  # noqa T201

redis_dependency = Mock()


@cache_for(timedelta(seconds=1))
def fn(number: Optional[int] = None) -> int:
    return mocked_dependency(number)


@cache_for(timedelta(milliseconds=200), background_refresh=True)
def fn_background(number: float) -> int:
    order_of_events("Background task started")
    value = mocked_dependency()
    mocked_dependency.return_value += 1
    sleep(number)

    order_of_events("Background task finished")
    return value


# TTL of 0 means every call after the initial priming call is considered stale, so a background
# refresh is triggered deterministically without sleeping to wait out a timer.
@cache_for(timedelta(seconds=0), background_refresh=True)
def fn_redis_background() -> list[str]:
    return redis_dependency()


@cache_for(timedelta(seconds=1))
def fn_redis_sync() -> list[str]:
    return redis_dependency()


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time() + timeout
    while time() < deadline:
        if predicate():
            return True
        sleep(0.01)
    return predicate()


class TestCacheUtils(APIBaseTest):
    def setUp(self):
        mocked_dependency.reset_mock()
        mocked_dependency.return_value = 1
        order_of_events.reset_mock()
        redis_dependency.reset_mock(return_value=True, side_effect=True)
        fn_redis_background.clear_cache()
        fn_redis_sync.clear_cache()

    def test_cache_for_with_different_passed_arguments_styles_when_skipping_cache(self) -> None:
        assert 1 == fn(use_cache=False)
        assert 1 == fn(2, use_cache=False)
        assert 1 == fn(number=2, use_cache=False)
        assert 1 == fn(number=2, use_cache=False)

        assert mocked_dependency.call_count == 4

    def test_cache_for_with_different_passed_arguments_styles_when_caching(self) -> None:
        assert 1 == fn(2, use_cache=True)
        assert 1 == fn(number=2, use_cache=True)
        assert 1 == fn(number=2, use_cache=True)

        # cache treats fn(2) and fn(number=2) as two different calls
        assert mocked_dependency.call_count == 2

    def test_background_cache_refresh(self) -> None:
        # First call is not cached and as such takes some time
        assert mocked_dependency.call_count == 0

        order_of_events("Inital call 1")
        assert 1 == fn_background(1, use_cache=True)
        assert mocked_dependency.call_count == 1

        order_of_events("Inital call 2")
        assert 1 == fn_background(1, use_cache=True)
        assert mocked_dependency.call_count == 1

        order_of_events("Inital call 3")
        assert 1 == fn_background(1, use_cache=True)
        assert mocked_dependency.call_count == 1

        # Let the cache timer expire so we trigger a background refresh
        sleep(0.3)
        assert mocked_dependency.call_count == 1  # but we know the cache is being refreshed
        order_of_events("Expired call 1")
        assert 1 == fn_background(1, use_cache=True)  # old return value

        # Let the cache timer expire again...
        sleep(0.5)
        order_of_events("Expired call 2")
        assert 1 == fn_background(1, use_cache=True)  # we still get the old return value

        sleep(0.6)  # Let the refresh complete
        order_of_events("Post refresh call 1")
        assert 2 == fn_background(1, use_cache=True)  # We get the new return value

        assert [x[0][0] for x in order_of_events.call_args_list] == [
            "Inital call 1",
            "Background task started",
            "Background task finished",
            "Inital call 2",
            "Inital call 3",
            "Expired call 1",
            "Background task started",
            "Expired call 2",
            "Background task finished",
            "Post refresh call 1",
        ]

    def test_background_refresh_swallows_transient_redis_connection_error(self) -> None:
        # Prime the cache with a good value while Redis is healthy.
        redis_dependency.return_value = ["team_a"]
        assert fn_redis_background(use_cache=True) == ["team_a"]

        # Redis master briefly refuses connections; the background refresh now hits a ConnectionError.
        redis_dependency.side_effect = redis.exceptions.ConnectionError("Connection closed by server")

        unhandled_thread_exceptions: list = []
        original_excepthook = threading.excepthook
        threading.excepthook = lambda args: unhandled_thread_exceptions.append(args)
        try:
            with patch("posthog.cache_utils.logger") as mock_logger:
                # Call while stale: this kicks off the background refresh and must keep serving the cached value.
                assert fn_redis_background(use_cache=True) == ["team_a"]
                assert _wait_until(lambda: mock_logger.warning.called), "background refresh should log and skip"
        finally:
            threading.excepthook = original_excepthook

        # The transient error must not escape the daemon thread (which would capture a spurious issue).
        assert unhandled_thread_exceptions == []
        # And the last cached value keeps being served.
        assert fn_redis_background(use_cache=True) == ["team_a"]

    def test_synchronous_refresh_propagates_redis_connection_error(self) -> None:
        # With no cached value to fall back on, the error must reach the caller rather than be swallowed.
        redis_dependency.side_effect = redis.exceptions.ConnectionError("Connection closed by server")
        with self.assertRaises(redis.exceptions.ConnectionError):
            fn_redis_sync(use_cache=True)
