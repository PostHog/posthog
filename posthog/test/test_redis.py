import asyncio

from unittest.mock import ANY, AsyncMock, patch

from django.test.testcases import TestCase

import fakeredis
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    InvalidResponse,
)

from posthog.redis import TEST_clear_clients, _client_map, _loop_clients, get_async_client, get_client


class TestRedis(TestCase):
    def setUp(self) -> None:
        super().setUp()
        TEST_clear_clients()
        _loop_clients.clear()

    @patch("fakeredis.FakeRedis")
    def test_redis_client_is_created(self, mock_fakeredis):
        from unittest.mock import Mock

        mock_instance = Mock()
        mock_fakeredis.return_value = mock_instance

        with self.settings(REDIS_URL="redis://mocked:6379"):
            client = get_client()

        assert client == mock_instance
        assert _client_map == {
            "redis://mocked:6379": mock_instance,
        }
        mock_fakeredis.assert_called_once()

    def test_redis_client_uses_given_url(self):
        with self.settings(REDIS_URL="redis://mocked:6379"):
            assert get_client("redis://other:6379")

        assert _client_map == {
            "redis://other:6379": ANY,
        }

    def test_redis_client_is_cached_between_calls(self):
        # Test sync client caching
        with patch("fakeredis.FakeRedis", wraps=fakeredis.FakeRedis) as spy_fakeredis:
            with self.settings(REDIS_URL="redis://mocked:6379"):
                # Ask for the client, none cached, create one
                assert get_client()
                spy_fakeredis.assert_called_once()
                spy_fakeredis.reset_mock()
                # Ask once more, for the same URL, get cached one
                assert get_client()
                spy_fakeredis.assert_not_called()
                # Ask for a different URL, create a new one
                assert get_client("redis://other:6379")
                spy_fakeredis.assert_called_once()

    def test_async_redis_client_is_cached_between_calls_test_mode(self):
        # Test async client caching in test mode (simple caching)
        with self.settings(REDIS_URL="redis://mocked:6379"):
            # Ask for the client, none cached, create one
            client1 = get_async_client()
            assert client1 is not None

            # Ask once more, for the same URL, get cached one (should be same instance)
            client2 = get_async_client()
            assert client2 is client1  # Should be same instance due to caching

            # Ask for a different URL, create a new one
            client3 = get_async_client("redis://other:6379")
            assert client3 is not client1  # Should be different instance

    def test_async_redis_client_production_behavior(self):
        # Test the production behavior with per-loop caching
        with patch("redis.asyncio.from_url") as mock_from_url:
            # Return different mock objects for each call
            mock_client1 = AsyncMock()
            mock_client2 = AsyncMock()
            mock_from_url.side_effect = [mock_client1, mock_client2]

            with self.settings(TEST=False, REDIS_URL="redis://mocked:6379"):

                async def runner():
                    # Within the same loop, should get same instance
                    c1 = get_async_client()
                    c2 = get_async_client()
                    self.assertIs(c1, c2)
                    return c1

                # Run in two different event loops
                client1 = asyncio.run(runner())
                client2 = asyncio.run(runner())

                # Different loops should get different client instances
                self.assertIsNot(client1, client2)
                # Should have been called twice (once per loop)
                self.assertEqual(mock_from_url.call_count, 2)
                # Verify the calls were made with correct parameters
                args, kwargs = mock_from_url.call_args_list[0]
                self.assertEqual(args, ("redis://mocked:6379",))
                self.assertEqual(kwargs["db"], 0)
                # The async client backs long-lived blocking consumers (e.g. notebooks
                # XREAD BLOCK), so it must NOT get a read socket_timeout — that would abort
                # a blocking read early. It still retries on a desynced connection.
                self.assertNotIn("socket_timeout", kwargs)
                self.assertEqual(kwargs["health_check_interval"], 30)
                self.assertIn(InvalidResponse, kwargs["retry_on_error"])

    def test_sync_redis_client_production_config_is_hardened(self):
        # The InvalidResponse "Protocol Error" desync that motivated this config surfaced on
        # the sync client: it needs a read timeout so a hung mid-response read can't block
        # forever, and a retry on InvalidResponse/ConnectionError so a dirty connection is
        # reset and reconnected instead of propagating the error.
        with patch("redis.from_url") as mock_from_url:
            with self.settings(TEST=False, REDIS_URL="redis://mocked:6379"):
                get_client()

        args, kwargs = mock_from_url.call_args
        self.assertEqual(args, ("redis://mocked:6379",))
        self.assertEqual(kwargs["db"], 0)
        self.assertEqual(kwargs["socket_timeout"], 5)
        self.assertEqual(kwargs["health_check_interval"], 30)
        self.assertIn(InvalidResponse, kwargs["retry_on_error"])
        self.assertIn(RedisConnectionError, kwargs["retry_on_error"])

    def test_same_loop_returns_cached_client_test_mode(self):
        """In test mode, calling get_async_client twice returns the same cached instance."""

        async def runner():
            c1 = get_async_client("redis://mocked:6379")
            c2 = get_async_client("redis://mocked:6379")
            self.assertIs(c1, c2)

        asyncio.run(runner())

    def test_different_loops_get_same_cached_client_test_mode(self):
        """In test mode, different event-loops get the same cached client for simplicity."""

        async def get_client():
            return get_async_client("redis://mocked:6379")

        c1 = asyncio.run(get_client())
        c2 = asyncio.run(get_client())

        # In test mode with simple caching, same URL returns same instance
        self.assertIs(c1, c2)
