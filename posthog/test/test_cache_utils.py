from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from functools import partial
from time import sleep
from typing import Any, Optional

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from posthog.cache_utils import MAX_REFRESH_BACKOFF, cache_for

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


failing_dependency = Mock()


@cache_for(timedelta(minutes=5), background_refresh=True)
def fn_background_failing() -> int:
    return failing_dependency()


class InlineThread:
    """Stands in for threading.Thread and runs the target inline, so the tests need no real thread."""

    def __init__(
        self,
        started: list["InlineThread"],
        target: Callable[..., None],
        kwargs: dict[str, Any] | None = None,
        name: str | None = None,
        daemon: bool = False,
    ) -> None:
        self._started = started
        self._target = target
        self._kwargs = kwargs or {}
        self.name = name
        self.daemon = daemon

    def start(self) -> None:
        self._started.append(self)
        self._target(**self._kwargs)


@contextmanager
def inline_threads() -> Iterator[list[InlineThread]]:
    started: list[InlineThread] = []

    with patch("posthog.cache_utils.threading.Thread", partial(InlineThread, started)):
        yield started


class TestFailingBackgroundRefresh(SimpleTestCase):
    def setUp(self):
        fn_background_failing.clear_cache()
        failing_dependency.reset_mock(side_effect=True)
        failing_dependency.return_value = 1

    def test_failed_background_refresh_does_not_raise_and_backs_off(self) -> None:
        with time_machine.travel("2026-01-01 00:00:00", tick=False) as frozen_time:
            assert 1 == fn_background_failing(use_cache=True)

            failing_dependency.side_effect = Exception("the refresh failed")
            frozen_time.shift(timedelta(minutes=6))

            with inline_threads() as started:
                assert 1 == fn_background_failing(use_cache=True)
                assert len(started) == 1
                assert started[0].daemon is True

                assert 1 == fn_background_failing(use_cache=True)
                assert len(started) == 1

                frozen_time.shift(MAX_REFRESH_BACKOFF)
                failing_dependency.side_effect = None
                failing_dependency.return_value = 2

                assert 2 == fn_background_failing(use_cache=True)
                assert len(started) == 2

    def test_first_call_still_raises(self) -> None:
        failing_dependency.side_effect = Exception("the first call failed")

        with self.assertRaises(Exception):
            fn_background_failing(use_cache=True)
