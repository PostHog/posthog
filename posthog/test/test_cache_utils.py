import threading
from datetime import timedelta
from time import sleep
from typing import Optional

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import Mock

from posthog.cache_utils import cache_for

mocked_dependency = Mock()
mocked_dependency.return_value = 1

order_of_events = Mock(side_effect=lambda x: print(x))  # noqa T201


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


class TestCacheUtils(APIBaseTest):
    def setUp(self):
        mocked_dependency.reset_mock()
        mocked_dependency.return_value = 1
        order_of_events.reset_mock()

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

    def test_background_refresh_failure_does_not_surface_uncaught_thread_exception(self) -> None:
        calls = {"count": 0}

        @cache_for(timedelta(seconds=30), background_refresh=True)
        def flaky() -> str:
            calls["count"] += 1
            if calls["count"] == 1:
                return "good"
            # Simulate Redis briefly going away during a background refresh.
            raise ConnectionRefusedError("redis unavailable")

        thread_exceptions: list[type] = []
        original_hook = threading.excepthook
        threading.excepthook = lambda a: thread_exceptions.append(a.exc_type)
        try:
            with freeze_time("2026-07-06 09:46:00") as frozen:
                assert flaky(use_cache=True) == "good"
                assert calls["count"] == 1

                # Expire the TTL so the next call kicks off a background refresh.
                frozen.tick(timedelta(seconds=31))
                before = set(threading.enumerate())
                # Caller keeps getting the last good value while the refresh runs.
                assert flaky(use_cache=True) == "good"
                for t in set(threading.enumerate()) - before:
                    t.join(timeout=5)

            # The refresh was attempted and failed, but the failure was swallowed
            # rather than re-raised into the detached thread.
            assert calls["count"] == 2
            assert thread_exceptions == []
        finally:
            threading.excepthook = original_hook
