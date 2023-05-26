import zlib
from django_redis.compressors.zlib import ZlibCompressor

from django.conf import settings

import structlog

logger = structlog.get_logger(__name__)


class TolerantZlibCompressor(ZlibCompressor):
    """
    If the compressor is turned on then values written to the cache will be compressed using zlib.
    If it is then turned off or removed we can't read those values anymore.
    This compressor is a tolerant reader and will return the original value if it can't be decompressed.

    The underlying zlib compressor doesn't compress every value it sends so, we're safe to have mixed values.
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
