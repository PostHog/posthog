from unittest import TestCase
from unittest.mock import MagicMock, patch

import redis
from celery import Celery
from parameterized import parameterized
from redbeat.schedulers import get_redis

from posthog.celery_redbeat import install_redbeat_redis_client, wait_for_redis


class TestInstallRedBeatRedisClient(TestCase):
    def test_redbeat_uses_the_retrying_client(self) -> None:
        app = Celery(set_as_current=False)
        app.conf.broker_url = "redis://redis.example.com:6379/0"

        install_redbeat_redis_client(app)

        client = get_redis(app)
        with (
            patch.object(redis.connection.AbstractConnection, "connect"),
            patch.object(redis.connection.AbstractConnection, "can_read", return_value=False),
            patch("redis.retry.sleep"),
            patch.object(
                redis.Redis,
                "_send_command_parse_response",
                side_effect=[
                    redis.exceptions.ConnectionError("Error -3 connecting to redis.example.com:6379"),
                    redis.exceptions.ReadOnlyError("You can't write against a read only replica."),
                    True,
                ],
            ),
        ):
            assert client.ping() is True
        assert client.connection_pool.connection_kwargs["health_check_interval"] > 0

    def test_leaves_sentinel_setups_to_redbeat(self) -> None:
        app = Celery(set_as_current=False)
        app.conf.broker_url = "redis-sentinel://redis.example.com:26379/0"

        install_redbeat_redis_client(app)

        assert getattr(app, "redbeat_redis", None) is None


class TestWaitForRedis(TestCase):
    @parameterized.expand(
        [
            (
                "recovers",
                [redis.exceptions.ConnectionError("dns"), redis.exceptions.TimeoutError("slow"), True],
                60,
                True,
            ),
            ("gives_up_at_deadline", redis.exceptions.ConnectionError("dns"), 0, False),
        ]
    )
    def test_wait_for_redis(self, _name: str, ping_side_effect: object, timeout: float, expected: bool) -> None:
        client = MagicMock()
        client.ping.side_effect = ping_side_effect

        with patch("posthog.celery_redbeat.time.sleep"):
            assert wait_for_redis(client, timeout_seconds=timeout, retry_interval_seconds=5) is expected
