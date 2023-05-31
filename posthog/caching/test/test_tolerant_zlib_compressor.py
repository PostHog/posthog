from django.test import TestCase
from parameterized import parameterized

from posthog.caching.tolerant_zlib_compressor import TolerantZlibCompressor


class TestTolerantZlibCompressor(TestCase):
    # compressors take an options in init but don't use it 🤷
    compressor = TolerantZlibCompressor({})

    short_uncompressed_bytes = b"hello world"
    # needs to be long enough to trigger compression
    uncompressed_bytes = b"hello world hello world hello world hello world hello world"
    compressed_bytes = b"x\x9c\xcbH\xcd\xc9\xc9W(\xcf/\xcaIQ\xc8 \x8d\r\x00\x9cy\x16M"

    @parameterized.expand(
        [
            ("test_when_disabled_compress_is_the_identity", False, uncompressed_bytes, uncompressed_bytes),
            ("test_when_enabled_can_compress", True, uncompressed_bytes, compressed_bytes),
            (
                "test_when_enabled_does_not_compress_small_values",
                True,
                short_uncompressed_bytes,
                short_uncompressed_bytes,
            ),
        ]
    )
    def test_the_zlib_compressor_compression(self, _, setting: bool, input: bytes, output: bytes) -> None:
        with self.settings(USE_REDIS_COMPRESSION=setting):
            assert self.compressor.compress(input) == output

    @parameterized.expand(
        [
            ("test_when_disabled_decompress_is_the_identity", False, uncompressed_bytes, uncompressed_bytes),
            ("test_when_enabled_can_decompress", True, compressed_bytes, uncompressed_bytes),
            ("test_when_disabled_can_still_decompress", False, compressed_bytes, uncompressed_bytes),
        ]
    )
    def test_the_zlib_compressor_decompression(self, _, setting: bool, input: bytes, output: bytes) -> None:
        with self.settings(USE_REDIS_COMPRESSION=setting):
            assert self.compressor.decompress(input) == output
