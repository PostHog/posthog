import os
from tempfile import mkstemp

import pytest

from posthog.temporal.delete_recordings.activities import overwrite_block


@pytest.mark.parametrize("buffer_size", [1, 64, 1024, 2048])
@pytest.mark.parametrize(
    "start_byte,block_length,input_buffer,expected_output_buffer",
    [
        (0, 5, bytearray(b"\x01" * 5 + b"\x02" * 5 + b"\x03" * 5), bytearray(b"\x00" * 5 + b"\x02" * 5 + b"\x03" * 5)),
        (5, 5, bytearray(b"\x01" * 5 + b"\x02" * 5 + b"\x03" * 5), bytearray(b"\x01" * 5 + b"\x00" * 5 + b"\x03" * 5)),
        (10, 5, bytearray(b"\x01" * 5 + b"\x02" * 5 + b"\x03" * 5), bytearray(b"\x01" * 5 + b"\x02" * 5 + b"\x00" * 5)),
        (0, 15, bytearray(b"\x01" * 5 + b"\x02" * 5 + b"\x03" * 5), bytearray(b"\x00" * 15)),
        (
            150,
            500,
            bytearray(b"\x01" * 150 + b"\x02" * 500 + b"\x03" * 5),
            bytearray(b"\x01" * 150 + b"\x00" * 500 + b"\x03" * 5),
        ),
        (0, 655, bytearray(b"\x01" * 150 + b"\x02" * 500 + b"\x03" * 5), bytearray(b"\x00" * 655)),
    ],
)
def test_overwrite_block(
    start_byte: int, block_length: int, buffer_size: int, input_buffer: bytearray, expected_output_buffer: bytearray
):
    _, tmpfile = mkstemp()

    with open(tmpfile, "wb") as fp:
        fp.write(input_buffer)

    overwrite_block(tmpfile, start_byte, block_length, buffer_size)

    with open(tmpfile, "rb") as fp:
        output_buffer = bytearray(fp.read())

    assert output_buffer == expected_output_buffer

    os.remove(tmpfile)
