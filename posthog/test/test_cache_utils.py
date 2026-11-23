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
        refresh_started = threading.Event()
        refresh_released = threading.Event()
        refresh_released.set()

        @cache_for(timedelta(milliseconds=200), background_refresh=True)
        def fn_background() -> int:
            value = dependency()
            refresh_started.set()
            assert refresh_released.wait(timeout=10), "the test never released the background refresh"
            return value

        with time_machine.travel(datetime(2026, 1, 1, tzinfo=UTC), tick=False) as traveller:
            assert 1 == fn_background(use_cache=True)
            assert 1 == fn_background(use_cache=True)
            assert dependency.call_count == 1

            refresh_started.clear()
            refresh_released.clear()
            try:
                traveller.shift(timedelta(milliseconds=300))
                assert 1 == fn_background(use_cache=True)
                assert refresh_started.wait(timeout=5)
                assert dependency.call_count == 2

                traveller.shift(timedelta(milliseconds=500))
                assert 1 == fn_background(use_cache=True)
                assert dependency.call_count == 2
            finally:
                refresh_released.set()

            wait_until(
                lambda: fn_background(use_cache=True) == 2,
                message="the background refresh never stored the new value",
            )
            assert dependency.call_count == 2
