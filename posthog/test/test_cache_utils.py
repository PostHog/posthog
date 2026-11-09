import threading
from datetime import UTC, datetime, timedelta
from typing import Optional

import time_machine
from unittest.mock import Mock

from django.test import SimpleTestCase

from posthog.cache_utils import cache_for
from posthog.test.waiting import wait_until

mocked_dependency = Mock()
mocked_dependency.return_value = 1


@cache_for(timedelta(seconds=1))
def fn(number: Optional[int] = None) -> int:
    return mocked_dependency(number)


class TestCacheUtils(SimpleTestCase):
    def setUp(self):
        fn.clear_cache()
        mocked_dependency.reset_mock()
        mocked_dependency.return_value = 1

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
        dependency = Mock(side_effect=[1, 2])
        order_of_events: list[str] = []
        refresh_started = threading.Event()
        refresh_released = threading.Event()
        refresh_released.set()

        @cache_for(timedelta(milliseconds=200), background_refresh=True)
        def fn_background() -> int:
            order_of_events.append("Background task started")
            refresh_started.set()
            value = dependency()
            refresh_released.wait()
            order_of_events.append("Background task finished")
            return value

        with time_machine.travel(datetime(2026, 1, 1, tzinfo=UTC), tick=False) as traveller:
            order_of_events.append("Initial call 1")
            assert 1 == fn_background(use_cache=True)
            assert dependency.call_count == 1

            order_of_events.append("Initial call 2")
            assert 1 == fn_background(use_cache=True)
            assert dependency.call_count == 1

            order_of_events.append("Initial call 3")
            assert 1 == fn_background(use_cache=True)
            assert dependency.call_count == 1

            refresh_started.clear()
            refresh_released.clear()
            try:
                traveller.shift(timedelta(milliseconds=300))
                assert dependency.call_count == 1
                order_of_events.append("Expired call 1")
                assert 1 == fn_background(use_cache=True)
                assert refresh_started.wait(timeout=5)

                traveller.shift(timedelta(milliseconds=500))
                order_of_events.append("Expired call 2")
                assert 1 == fn_background(use_cache=True)
            finally:
                refresh_released.set()

            wait_until(
                lambda: fn_background(use_cache=True) == 2,
                message="the background refresh never stored the new value",
            )
            order_of_events.append("Post refresh call 1")
            assert 2 == fn_background(use_cache=True)

        assert order_of_events == [
            "Initial call 1",
            "Background task started",
            "Background task finished",
            "Initial call 2",
            "Initial call 3",
            "Expired call 1",
            "Background task started",
            "Expired call 2",
            "Background task finished",
            "Post refresh call 1",
        ]
