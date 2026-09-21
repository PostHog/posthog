"""Extract the initramfs that the stock v86 Buildroot kernel embeds, so the new kernel keeps the same userland."""

from __future__ import annotations

import re
import sys
import zlib
import hashlib
from pathlib import Path

STOCK_SHA256 = "7befbaea31e249d9a518c4b95fa42b2a193d0e3de46250d617cbdeb866ee28b0"
GZIP_MAGIC = b"\x1f\x8b\x08"
CPIO_MAGIC = b"070701"


def gunzip_at(data: bytes, offset: int) -> bytes | None:
    try:
        return zlib.decompressobj(31).decompress(data[offset:])
    except zlib.error:
        return None


def first_payload(data: bytes, minimum: int, prefix: bytes = b"") -> bytes:
    for match in re.finditer(re.escape(GZIP_MAGIC), data):
        payload = gunzip_at(data, match.start())
        if payload and len(payload) >= minimum and payload.startswith(prefix):
            return payload
    raise ValueError("No matching gzip payload")


def main(source: Path, target: Path) -> None:
    image = source.read_bytes()
    if hashlib.sha256(image).hexdigest() != STOCK_SHA256:
        raise ValueError(f"Checksum mismatch: {source}")
    vmlinux = first_payload(image, 1_000_000)
    target.write_bytes(first_payload(vmlinux, 1_000_000, CPIO_MAGIC))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
