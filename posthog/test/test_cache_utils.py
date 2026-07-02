import threading
from datetime import timedelta
from time import sleep
from typing import Optional

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import Mock

import redis.exceptions

from posthog.cache_utils import cache_for

mocked_dependency = Mock()
mocked_dependency.return_value = 1

order_of_events = Mock(side_effect=lambda x: print(x))  # noqa T201

flaky_dependency = Mock()


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


@cache_for(timedelta(seconds=1), background_refresh=True)
def fn_flaky_background() -> int:
    return flaky_dependency()


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

    def test_background_refresh_survives_transient_connection_error(self) -> None:
        fn_flaky_background.clear_cache()
        flaky_dependency.reset_mock(side_effect=True)
        flaky_dependency.return_value = 1

        captured_thread_exceptions: list[BaseException | None] = []
        original_hook = threading.excepthook
        threading.excepthook = lambda args: captured_thread_exceptions.append(args.exc_value)

        try:
            with freeze_time("2024-01-01 00:00:00") as frozen:
                # Prime the cache with a good value.
                assert fn_flaky_background(use_cache=True) == 1

                # Redis master goes momentarily unreachable, then the cache goes stale.
                flaky_dependency.side_effect = redis.exceptions.ConnectionError("master unreachable")
                frozen.tick(timedelta(seconds=2))

                # Stale value triggers a background refresh; the request thread keeps serving the
                # last cached value rather than raising.
                assert fn_flaky_background(use_cache=True) == 1

            # Wait for the background refresh thread to finish so excepthook has a chance to fire.
            for thread in threading.enumerate():
                if thread is not threading.current_thread() and thread is not threading.main_thread():
                    thread.join(timeout=5)
        finally:
            threading.excepthook = original_hook

        # The transient connection error must not have escaped the background thread.
        assert captured_thread_exceptions == []
        # And we keep serving the last good value.
        assert fn_flaky_background(use_cache=True) == 1
