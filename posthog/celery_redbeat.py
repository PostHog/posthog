import time

from django.conf import settings

import redis
from celery import Celery
from celery.utils.log import get_logger
from redbeat import RedBeatScheduler
from redbeat.schedulers import REDBEAT_REDIS_KEY, ensure_conf, get_redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry

logger = get_logger("celery.beat")

# Backoff of 1, 2, 4, 8, 8, 8 seconds. The total stays well below the RedBeat lock timeout
# (5 x CELERY_BEAT_MAX_LOOP_INTERVAL), so a retried lock extend still runs while beat owns the lock.
REDIS_RETRIES = 6
REDIS_RETRY_BACKOFF = ExponentialBackoff(cap=8, base=0.5)
REDIS_HEALTH_CHECK_INTERVAL_SECONDS = 10
STARTUP_WAIT_SECONDS = 120
STARTUP_WAIT_RETRY_INTERVAL_SECONDS = 5


def install_redbeat_redis_client(app: Celery) -> None:
    """Give RedBeat a Redis client that retries short outages.

    RedBeat creates a plain client with no retries and no health check, so one dropped
    connection during a tick or a lock extend crashes beat. RedBeat caches its client on
    the app, so a client set here first is the client RedBeat uses for all calls.
    """
    conf = ensure_conf(app)
    if getattr(app, REDBEAT_REDIS_KEY, None) is not None:
        return
    # Cluster, sentinel and custom SSL setups need RedBeat's own client construction.
    if not conf.redis_url.startswith(("redis://", "rediss://")) or conf.redbeat_redis_options or conf.redis_use_ssl:
        return

    client = redis.Redis.from_url(
        conf.redis_url,
        decode_responses=True,
        socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=settings.REDIS_SOCKET_TIMEOUT_SECONDS,
        health_check_interval=REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
        retry=Retry(REDIS_RETRY_BACKOFF, REDIS_RETRIES),
        # ReadOnlyError comes from a connection that still points at a demoted primary after
        # a failover. A reconnect reaches the new primary.
        retry_on_error=[
            redis.exceptions.ConnectionError,
            redis.exceptions.TimeoutError,
            redis.exceptions.ReadOnlyError,
        ],
    )
    setattr(app, REDBEAT_REDIS_KEY, client)


def wait_for_redis(client: redis.Redis, timeout_seconds: float, retry_interval_seconds: float) -> bool:
    """Ping Redis until it answers or the timeout expires. Return True if Redis answered."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            client.ping()
            return True
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
            if time.monotonic() >= deadline:
                logger.warning("beat: Redis is still not reachable after %ss, starting anyway: %s", timeout_seconds, e)
                return False
            logger.warning("beat: Redis is not reachable, retrying in %ss: %s", retry_interval_seconds, e)
            time.sleep(retry_interval_seconds)


class ResilientRedBeatScheduler(RedBeatScheduler):
    def setup_schedule(self) -> None:
        install_redbeat_redis_client(self.app)
        # Beat restarts in a loop while Redis is down at startup, and each crash reports an
        # exception. A wait here replaces that loop with log lines until Redis is ready.
        wait_for_redis(get_redis(self.app), STARTUP_WAIT_SECONDS, STARTUP_WAIT_RETRY_INTERVAL_SECONDS)
        super().setup_schedule()
