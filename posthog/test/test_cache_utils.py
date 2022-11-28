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
    def setUp(self):
        mocked_dependency.reset_mock()

    def test_cache_for_with_different_passed_arguments_styles_when_skipping_cache(self) -> None:
        assert 1 == test_func(use_cache=False)
        assert 1 == test_func(2, use_cache=False)
        assert 1 == test_func(number=2, use_cache=False)
        assert 1 == test_func(number=2, use_cache=False)

        assert mocked_dependency.call_count == 4

    def test_cache_for_with_different_passed_arguments_styles_when_caching(self) -> None:
        assert 1 == test_func(2, use_cache=True)
        assert 1 == test_func(number=2, use_cache=True)
        assert 1 == test_func(number=2, use_cache=True)

        # cache treats test_func(2) and test_func(number=2) as two different calls
        assert mocked_dependency.call_count == 2
