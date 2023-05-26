import zlib

from django_redis.compressors.base import BaseCompressor

from django.conf import settings

import structlog

logger = structlog.get_logger(__name__)


class TolerantZlibCompressor(BaseCompressor):
    """
    If the compressor is turned on then values written to the cache will be compressed using zlib.
    If it is subsequently turned off we still want to be able to read compressed values from the cache.
    Even while we no longer write compressed values to the cache.

    This compressor is a tolerant reader and will return the original value if it can't be decompressed.
    """

    min_length = 15
    preset = 6

    def compress(self, value: bytes) -> bytes:
        if settings.USE_REDIS_COMPRESSION and len(value) > self.min_length:
            return zlib.compress(value, self.preset)
        return value

    def decompress(self, value: bytes) -> bytes:
        try:
            return zlib.decompress(value)
        except zlib.error:
            # if the decompression fails, behave like the IdentityCompressor
            logger.warning("tolerant_zlib_compressor - failed to decompress value from redis, returning original value")
            return value
