from django.conf import settings

import zstd
import structlog
from django_redis.compressors.base import BaseCompressor
from prometheus_client import Counter

logger = structlog.get_logger(__name__)

# Every zstd frame starts with this magic number (RFC 8878, section 3.1.1).
ZSTD_FRAME_MAGIC = b"\x28\xb5\x2f\xfd"

COULD_NOT_DECOMPRESS_VALUE_COUNTER = Counter(
    "posthog_redis_could_not_decompress_value_counter",
    "Zstd frames read from redis that this decoder could not decompress. The caller gets "
    "the compressed bytes in place of its value, so any sustained rate is a defect.",
)


class ZstdCompressor(BaseCompressor):
    """
    Compressor that uses zstd for compression.
    If the compressor is turned on then values written to the cache will be compressed using zstd.
    If it is subsequently turned off we still want to be able to read compressed values from the cache.
    Even while we no longer write compressed values to the cache.

    This compressor will return the original value if it can't be decompressed.
    """

    # we don't want to compress all values, e.g. feature flag cache in decide is already small
    min_length = 512
    zstd_preset = 0
    zstd_threads = 1

    def compress(self, value: bytes) -> bytes:
        if settings.USE_REDIS_COMPRESSION and len(value) > self.min_length:
            return zstd.compress(value, self.zstd_preset, self.zstd_threads)
        return value

    def decompress(self, value: bytes) -> bytes:
        # Values at or below min_length are stored raw, so most reads hand this method
        # something zstd never wrote. The magic number settles that without the decoder.
        if not value.startswith(ZSTD_FRAME_MAGIC):
            return value
        try:
            return zstd.decompress(value)
        except zstd.Error:
            # Counted whatever USE_REDIS_COMPRESSION says: old frames stay in redis after
            # compression is turned off, and turning it off is a plausible response to this.
            COULD_NOT_DECOMPRESS_VALUE_COUNTER.inc()
            # if the decompression fails, behave like the IdentityCompressor
            # this way if the compressor is turned off we can still read values
            return value
