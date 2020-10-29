import logging
from datetime import timedelta
from random import random
from typing import Optional

import redis
from django.conf import settings
from django.utils.timezone import now

logger = logging.getLogger(__name__)

_client = None


def get_client() -> Optional[redis.Redis]:
    global _client

    if _client is None:
        if settings.TEST:
            import fakeredis  # type: ignore

            server = fakeredis.FakeServer()
            _client = fakeredis.FakeStrictRedis(server=server)
            _client._server = server
        elif settings.REDIS_URL:
            _client = redis.from_url(settings.REDIS_URL, db=0)
    return _client


class GoldenRetriever:
    def __init__(self, key: str, default=set(), frequency=timedelta(minutes=1), typecast=int, client=get_client()):
        self.key = key
        self.frequency = frequency
        self.next_fetch_time = now() - frequency
        self.failure_count = 0
        self.cached_value = default
        self.typecast = typecast
        self.client = client

    def get(self):
        if now() >= self.next_fetch_time and self.client is not None:
            try:
                self.cached_value = set(map(self.typecast, self.client.lrange(self.key, 0, -1)))
                self.failure_count = 0
            except redis.RedisError as err:
                self.failure_count += 1
                logger.error(
                    f"Loading key failed, returning previous value. key='{self.key}' failure_count={self.failure_count} error={err}"
                )
            self.next_fetch_time = now() + self.frequency * (1 + random())

        return self.cached_value
