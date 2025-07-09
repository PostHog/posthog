from unittest.mock import ANY, patch
from posthog.redis import TEST_clear_clients, get_client, get_async_client, _client_map
import posthog.redis

from django.test.testcases import TestCase


class TestRedis(TestCase):
    def setUp(self) -> None:
        super().setUp()

        TEST_clear_clients()

    @patch("posthog.redis.redis")
    def test_redis_client_is_created(self, mock_redis):
        mock_redis.from_url.return_value = "test"

        with self.settings(REDIS_URL="redis://mocked:6379", TEST=False):
            client = get_client()

        assert client
        assert _client_map == {
            "redis://mocked:6379": "test",
        }
        mock_redis.from_url.assert_called_once_with("redis://mocked:6379", db=0)

    def test_redis_client_uses_given_url(self):
        with self.settings(REDIS_URL="redis://mocked:6379"):
            assert get_client("redis://other:6379")

        assert _client_map == {
            "redis://other:6379": ANY,
        }

    def test_redis_client_is_cached_between_calls(self):
        test_cases = [
            (get_client, "posthog.redis.redis.from_url", posthog.redis.redis.from_url),
            (get_async_client, "posthog.redis.aioredis.from_url", posthog.redis.aioredis.from_url),
        ]
        # Test both sync and async clients
        for client_func, patch_path, original_func in test_cases:
            # Isolate test cases
            with self.subTest(client_func=client_func.__name__):
                with patch(patch_path, wraps=original_func) as spy_from_url:
                    with self.settings(REDIS_URL="redis://mocked:6379", TEST=False):
                        # Ask for the client, none cached, create one
                        assert client_func()
                        spy_from_url.assert_called_once_with("redis://mocked:6379", db=0)
                        spy_from_url.reset_mock()
                        # Ask once more, for the same URL, get cached one
                        assert client_func()
                        spy_from_url.assert_not_called()
                        # Ask for a different URL, create a new one
                        assert client_func("redis://other:6379")
                        spy_from_url.assert_called_once_with("redis://other:6379", db=0)
