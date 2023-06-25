from unittest.mock import ANY, patch
from posthog.redis import TEST_clear_clients, get_client, _client_map

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

    @patch("posthog.redis.redis")
    def test_redis_client_is_cached_between_calls(self, mock_redis):
        mock_redis.from_url.return_value = "test"

        with self.settings(REDIS_URL="redis://mocked:6379", TEST=False):
            assert get_client()
            mock_redis.from_url.assert_called_once_with("redis://mocked:6379", db=0)
            mock_redis.from_url.reset_mock()

            assert get_client()
            mock_redis.from_url.assert_not_called()

            assert get_client("redis://other:6379")
            mock_redis.from_url.assert_called_once_with("redis://other:6379", db=0)
