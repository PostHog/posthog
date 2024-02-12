from django.test import TestCase
from parameterized import parameterized

from posthog.caching.tolerant_zlib_compressor import TolerantZlibCompressor


class TestTolerantZlibCompressor(TestCase):
    # compressors take an options in init but don't use it 🤷
    compressor = TolerantZlibCompressor({})

    short_uncompressed_bytes = b"hello world"
    # needs to be long enough to trigger compression
    uncompressed_bytes = ("hello world hello world hello world hello world hello world" * 100).encode("utf-8")
    compressed_bytes = b"x\x9c\xed\xcb\xb1\t\x00 \x0c\x00\xc1U2\x9cB\x8a@\xc0\xc6\xf5\x9d!\x95\xcdu_\xfc\xe5\xae\xea\xb8}jE\xcez\xb8\xa3(\x8a\xa2(\x8a\xa2(\x8a\xa2(\x8a\xa2(\x8a\xa2\xe8\x1f\xfa\x00\xaf\xed\xb6)"

    @parameterized.expand(
        [
            (
                "test_when_disabled_compress_is_the_identity",
                False,
                uncompressed_bytes,
                uncompressed_bytes,
            ),
            (
                "test_when_enabled_can_compress",
                True,
                uncompressed_bytes,
                compressed_bytes,
            ),
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
            compressed = self.compressor.compress(input)
            assert compressed == output

    @parameterized.expand(
        [
            (
                "test_when_disabled_decompress_is_the_identity",
                False,
                uncompressed_bytes,
                uncompressed_bytes,
            ),
            (
                "test_when_enabled_can_decompress",
                True,
                compressed_bytes,
                uncompressed_bytes,
            ),
            (
                "test_when_disabled_can_still_decompress",
                False,
                compressed_bytes,
                uncompressed_bytes,
            ),
        ]
    )
    def test_the_zlib_compressor_decompression(self, _, setting: bool, input: bytes, output: bytes) -> None:
        with self.settings(USE_REDIS_COMPRESSION=setting):
            assert self.compressor.decompress(input) == output
