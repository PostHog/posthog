from datetime import timedelta
from typing import Optional
from unittest.mock import Mock

from posthog.cache_utils import cache_for
from posthog.test.base import APIBaseTest

mocked_dependency = Mock()
mocked_dependency.return_value = 1


@cache_for(timedelta(seconds=1))
def test_func(number: Optional[int] = None) -> int:
    return mocked_dependency(number)


class TestCacheUtils(APIBaseTest):
    def test_cache_for_with_different_passed_arguments_styles_when_skipping_in_tests(self) -> None:
        with self.settings(TEST=True):
            assert 1 == test_func()
            assert 1 == test_func(2)
            assert 1 == test_func(number=2)
            assert 1 == test_func(number=2)

            # function is never cached when TEST=True
            assert mocked_dependency.call_count == 4

    def test_cache_for_with_different_passed_arguments_styles_when_caching(self) -> None:
        with self.settings(TEST=False):
            assert 1 == test_func(2)
            assert 1 == test_func(number=2)
            assert 1 == test_func(number=2)

            # cache treats test_func(2) and test_func(number=2) as two different calls
            assert mocked_dependency.call_count == 2
