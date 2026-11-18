import struct

from unittest.mock import patch

from django.test import SimpleTestCase

from celery.exceptions import SoftTimeLimitExceeded
from parameterized import parameterized

from posthog.caching.zstd_compressor import ZSTD_FRAME_MAGIC, ZstdCompressor


class TestZstdCompressor(SimpleTestCase):
    # compressors take an options in init but don't use it 🤷
    compressor = ZstdCompressor({})

    short_uncompressed_bytes = b"hello world"
    # needs to be long enough to trigger compression
    uncompressed_bytes = ("hello world hello world hello world hello world hello world" * 100).encode("utf-8")
    zlib_compressed_bytes = b"x\x9c\xed\xcb\xb1\t\x00 \x0c\x00\xc1U2\x9cB\x8a@\xc0\xc6\xf5\x9d!\x95\xcdu_\xfc\xe5\xae\xea\xb8}jE\xcez\xb8\xa3(\x8a\xa2(\x8a\xa2(\x8a\xa2(\x8a\xa2(\x8a\xa2\xe8\x1f\xfa\x00\xaf\xed\xb6)"
    zstd_compressed_bytes = b'(\xb5/\xfd`\x0c\x16\xbd\x02\x00`hello world \x80\xc7\xa8\xe0\xf77\xf0\x951\x12x\x81\xc1\xff\xbf\x7fDD\x94\x88\x880""JD\x84\x18\x11\x11%"D\x8c\x88\x88\x12!"FDD\t\x11\x11#""\x89\x88\x88\x11\x11\xa1DD\xc4\x88\x08Q""bD\x88(\x11\x11ed\xaa\xf9]\xa6'
    # Carries the frame magic and still fails to decompress, as a truncated frame does.
    unreadable_zstd_frame = zstd_compressed_bytes[:16]
    # Frames that fail outside zstd.Error. Header descriptor 0xe0 declares a single segment with
    # an 8-byte content size (RFC 8878, section 3.1.1.1), so the decoder trusts the size below it
    # and allocates before it reads any data. 2^62 exhausts the allocator and raises MemoryError.
    # 2^63 + 1 overflows a signed size and raises SystemError.
    unallocatable_content_size_frame = ZSTD_FRAME_MAGIC + b"\xe0" + struct.pack("<Q", 1 << 62)
    negative_content_size_frame = ZSTD_FRAME_MAGIC + b"\xe0" + struct.pack("<Q", (1 << 63) + 1)

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
                zstd_compressed_bytes,
            ),
            (
                "test_when_enabled_does_not_compress_small_values",
                True,
                short_uncompressed_bytes,
                short_uncompressed_bytes,
            ),
        ]
    )
    def test_the_zstd_compressor_compression(self, _, setting: bool, input: bytes, output: bytes) -> None:
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
                "test_when_enabled_can_decompress_zstd",
                True,
                zstd_compressed_bytes,
                uncompressed_bytes,
            ),
            (
                "test_when_disabled_can_still_decompress_zstd",
                False,
                zstd_compressed_bytes,
                uncompressed_bytes,
            ),
        ]
    )
    def test_the_zstd_compressor_decompression(self, _, setting: bool, input: bytes, output: bytes) -> None:
        with self.settings(USE_REDIS_COMPRESSION=setting):
            assert self.compressor.decompress(input) == output

    @parameterized.expand(
        [
            ("a_frame_that_will_not_decompress", unreadable_zstd_frame, 1),
            ("a_frame_declaring_a_content_size_that_cannot_be_allocated", unallocatable_content_size_frame, 1),
            ("a_frame_declaring_a_content_size_that_overflows", negative_content_size_frame, 1),
            ("a_value_that_was_never_compressed", short_uncompressed_bytes, 0),
        ]
    )
    def test_only_an_unreadable_zstd_frame_is_counted(self, _, input: bytes, expected_increments: int) -> None:
        for setting in (False, True):
            with (
                self.subTest(USE_REDIS_COMPRESSION=setting),
                self.settings(USE_REDIS_COMPRESSION=setting),
                patch("posthog.caching.zstd_compressor.COULD_NOT_DECOMPRESS_VALUE_COUNTER") as mock_counter,
            ):
                assert self.compressor.decompress(input) == input
                assert mock_counter.inc.call_count == expected_increments

    def test_soft_time_limit_during_decode_propagates(self) -> None:
        with (
            patch("posthog.caching.zstd_compressor.zstd.decompress", side_effect=SoftTimeLimitExceeded()),
            patch("posthog.caching.zstd_compressor.COULD_NOT_DECOMPRESS_VALUE_COUNTER") as mock_counter,
            self.assertRaises(SoftTimeLimitExceeded),
        ):
            self.compressor.decompress(self.zstd_compressed_bytes)

        mock_counter.inc.assert_not_called()
