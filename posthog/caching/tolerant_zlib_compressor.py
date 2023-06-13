import zlib

from django_redis.compressors.base import BaseCompressor

from django.conf import settings

import structlog
from prometheus_client import Counter

logger = structlog.get_logger(__name__)

COULD_NOT_DECOMPRESS_VALUE_COUNTER = Counter(
    "posthog_redis_could_not_decompress_value_counter",
    """
    Number of times decompression from redis failed while the setting was on.
    This is probably a sign that either there are still uncompressed values in redis
    or a value that was too small to compress and so doesn't need decompressing
    and so, seeing positive values here isn't necessarily an error.
    """,
)


class TolerantZlibCompressor(BaseCompressor):
    """
    If the compressor is turned on then values written to the cache will be compressed using zlib.
    If it is subsequently turned off we still want to be able to read compressed values from the cache.
    Even while we no longer write compressed values to the cache.

    This compressor is a tolerant reader and will return the original value if it can't be decompressed.
    """

    # we don't want to compress all values, e.g. feature flag cache in decide is already small
    min_length = 1024
    preset = 6

    def compress(self, value: bytes) -> bytes:
        if settings.USE_REDIS_COMPRESSION and len(value) > self.min_length:
            return zlib.compress(value, self.preset)
        return value

    def decompress(self, value: bytes) -> bytes:
        try:
            return zlib.decompress(value)
        except zlib.error:
            if settings.USE_REDIS_COMPRESSION:
                COULD_NOT_DECOMPRESS_VALUE_COUNTER.inc()
            # if the decompression fails, behave like the IdentityCompressor
            # this way if the compressor is turned off we can still read values
            return value
