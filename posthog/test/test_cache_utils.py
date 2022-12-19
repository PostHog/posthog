from datetime import timedelta
from typing import Optional
from unittest.mock import Mock, patch

from posthog.cache_utils import cache_for
from posthog.test.base import APIBaseTest

mocked_dependency = Mock()
mocked_dependency.return_value = 1


@cache_for(timedelta(seconds=1))
def test_func(number: Optional[int] = None) -> int:
    return mocked_dependency(number)


@cache_for(timedelta(seconds=1), redis_cache_key="test_key", redis_cache_time=timedelta(minutes=30))
def test_redis_func() -> int:
    return mocked_dependency()


class TestCacheUtils(APIBaseTest):
    def setUp(self):
        mocked_dependency.reset_mock()
        test_func._cache = {}
        test_redis_func._cache = {}

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

    @patch("posthog.cache_utils.cache")
    def test_redis_caching(self, mock_cache) -> None:
        mock_cache.get.return_value = None

        assert 1 == test_redis_func(use_cache=True)
        assert 1 == test_redis_func(use_cache=True)

        assert mocked_dependency.call_count == 1
        assert mock_cache.get.call_count == 1
        assert mock_cache.set.call_count == 1

    @patch("posthog.cache_utils.cache")
    def test_redis_caching_with_cached_result(self, mock_cache) -> None:
        mock_cache.get.return_value = 3

        self.setUp()

        assert 3 == test_redis_func(use_cache=True)
        assert 3 == test_redis_func(use_cache=True)

        assert mocked_dependency.call_count == 0
        assert mock_cache.get.call_count == 1
        assert mock_cache.set.call_count == 0
