from unittest.mock import ANY, patch

from posthog.redis import TEST_clear_clients, get_client, get_async_client, _client_map, _loop_clients

from django.test.testcases import TestCase
import asyncio
import fakeredis


class TestRedis(TestCase):
    def setUp(self) -> None:
        super().setUp()
        TEST_clear_clients()
        _loop_clients.clear()

    @patch("fakeredis.FakeRedis")
    def test_redis_client_is_created(self, mock_fakeredis):
        mock_instance = "test"
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

    def test_async_redis_client_is_cached_between_calls(self):
        # Test async client caching
        async def runner():
            with patch("fakeredis.FakeAsyncRedis", wraps=fakeredis.FakeAsyncRedis) as spy_fakeasyncredis:
                with self.settings(REDIS_URL="redis://mocked:6379"):
                    # Ask for the client, none cached, create one
                    assert get_async_client()
                    spy_fakeasyncredis.assert_called_once()
                    spy_fakeasyncredis.reset_mock()
                    # Ask once more, for the same URL, get cached one
                    assert get_async_client()
                    spy_fakeasyncredis.assert_not_called()
                    # Ask for a different URL, create a new one
                    assert get_async_client("redis://other:6379")
                    spy_fakeasyncredis.assert_called_once()

        asyncio.run(runner())

    def test_same_loop_returns_cached_client(self):
        """Calling get_async_client twice inside the same event-loop must return the identical object."""

        async def runner():
            c1 = get_async_client("redis://mocked:6379")
            c2 = get_async_client("redis://mocked:6379")
            self.assertIs(c1, c2)

        with patch("fakeredis.FakeAsyncRedis") as mocked:
            mock_instance = object()
            mocked.return_value = mock_instance
            asyncio.run(runner())
            # FakeAsyncRedis called only once – second call was served from cache
            mocked.assert_called_once()

    def test_different_loops_get_distinct_clients(self):
        """Each event-loop gets its own cached client – separate loops ⇒ separate objects."""

        async def get_client():
            return get_async_client("redis://mocked:6379")

        with patch("fakeredis.FakeAsyncRedis") as mocked:
            # Return different objects for each call
            mocked.side_effect = [object(), object()]
            c1 = asyncio.run(get_client())
            c2 = asyncio.run(get_client())

            self.assertIsNot(c1, c2)
            # called twice because two distinct loops instantiated their own pool
            self.assertEqual(mocked.call_count, 2)
