"""Canvas image asset store.

Uploaded image assets live in object storage under a content-addressed,
canvas-owned key. Source projects reference them by hash (an ``objectRef``
asset entry), so storage keys never appear in source and cannot be forged
across teams, and a stored source version stays reproducible because the
bytes behind a hash cannot change.
"""

import hashlib
from io import BytesIO
from typing import Any
from uuid import UUID

import structlog
import defusedxml.ElementTree as ET
from PIL import Image, features

from posthog.dataclasses import frozen
from posthog.storage import object_storage

from products.canvas.backend.contract import contract_limits
from products.canvas.backend.source import diagnostic

logger = structlog.get_logger(__name__)

_ASSET_CACHE_CONTROL = "private, max-age=31536000, immutable"

# Raster formats are verified by decoding with PIL, which catches truncated or
# mislabeled files.
_RASTER_MAGIC: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
]


class InvalidCanvasAsset(Exception):
    """The uploaded bytes are not a supported, well-formed image."""


@frozen
class StoredCanvasAsset:
    sha256: str
    content_type: str
    size_bytes: int


def canvas_asset_object_key(team_id: int, canvas_id: str | UUID, sha256: str) -> str:
    return f"canvas_asset/team_{team_id}/{canvas_id}/{sha256}"


# Cap the decoded pixel count to bound peak memory. A compressed image well under
# the byte limit can decode to hundreds of megabytes, which a shared web worker
# cannot absorb on every upload and read. 50 megapixels (about 7000x7000) is
# generous for a canvas image and rejects decompression bombs.
_MAX_IMAGE_PIXELS = 50_000_000


def _verify_raster(data: bytes) -> bool:
    try:
        with Image.open(BytesIO(data)) as image:
            # width and height come from the header, so reject an oversized image
            # before load() decodes every pixel.
            if image.width * image.height > _MAX_IMAGE_PIXELS:
                return False
            image.load()
        return True
    except Exception:
        return False


def _verify_svg(data: bytes) -> bool:
    """Well-formed XML whose root element is <svg>.

    Parsed with defusedxml, so a document that defines entities or references
    external ones is rejected rather than expanded. Text or HTML that merely
    contains "<svg" does not parse to an svg root and is rejected.
    """
    try:
        root = ET.fromstring(data)
    except Exception:
        return False
    return isinstance(root.tag, str) and root.tag.rsplit("}", 1)[-1] == "svg"


def sniff_image_content_type(data: bytes) -> str | None:
    """The content type of well-formed image bytes, or None.

    Detected from the bytes, never from a caller-supplied type: a mislabeled
    upload would otherwise be served under the forged type from the artifact
    origin.
    """
    for magic, content_type in _RASTER_MAGIC:
        if data.startswith(magic):
            return content_type if _verify_raster(data) else None
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp" if _verify_raster(data) else None
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        # Decode to reject a truncated or forged AVIF where the Pillow build
        # supports it; older builds without AVIF fall back to the signature.
        if features.check("avif"):
            return "image/avif" if _verify_raster(data) else None
        return "image/avif"
    head = data[:4096].lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"<") and b"<svg" in head:
        return "image/svg+xml" if _verify_svg(data) else None
    return None


def store_canvas_asset(team_id: int, canvas_id: str | UUID, data: bytes) -> StoredCanvasAsset:
    """Verify and write image bytes to the canvas's content-addressed store.

    Idempotent: the key is derived from the content hash, so re-uploading the
    same bytes rewrites the same object. Raises InvalidCanvasAsset for empty,
    oversized, or non-image bytes, and ObjectStorageError when storage is
    unavailable.
    """
    max_bytes = contract_limits()["maxAssetFileBytes"]
    if not data:
        raise InvalidCanvasAsset("The uploaded file is empty.")
    if len(data) > max_bytes:
        raise InvalidCanvasAsset(f"Images may be at most {max_bytes // (1024 * 1024)} MB.")
    content_type = sniff_image_content_type(data)
    if content_type is None:
        raise InvalidCanvasAsset("Only PNG, JPEG, GIF, WebP, AVIF, and SVG images are supported.")
    digest = hashlib.sha256(data).hexdigest()
    key = canvas_asset_object_key(team_id, canvas_id, digest)
    object_storage.write(key, data, extras={"ContentType": content_type, "CacheControl": _ASSET_CACHE_CONTROL})
    try:
        object_storage.tag(key, {"team_id": str(team_id), "canvas_id": str(canvas_id)})
    except Exception:
        logger.warning("canvas_asset_tag_failed", key=key)
    return StoredCanvasAsset(sha256=digest, content_type=content_type, size_bytes=len(data))


def read_canvas_asset(team_id: int, canvas_id: str | UUID, sha256: str) -> bytes | None:
    """The asset's bytes, integrity-checked against its content-addressed key."""
    data = object_storage.read_bytes(canvas_asset_object_key(team_id, canvas_id, sha256), missing_ok=True)
    if data is None or hashlib.sha256(data).hexdigest() != sha256:
        return None
    return data


def verify_referenced_assets(team_id: int, canvas_id: str | UUID, project: dict[str, Any]) -> list[dict[str, Any]]:
    """Publish-time existence check for every objectRef asset in the project.

    A reference to an object that is missing (or has drifted in size) would
    otherwise only fail later, inside the build worker.
    """
    diagnostics: list[dict[str, Any]] = []
    for path, asset in (project.get("assets") or {}).items():
        if not isinstance(asset, dict) or asset.get("encoding") != "objectRef":
            continue
        head = object_storage.head_object(canvas_asset_object_key(team_id, canvas_id, str(asset.get("sha256"))))
        if head is None:
            diagnostics.append(
                diagnostic(
                    "error",
                    "asset_missing",
                    f'asset "{path}" references an object that is not in this canvas\'s asset store — upload it first',
                    path=path,
                )
            )
        elif head.get("ContentLength") != asset.get("sizeBytes"):
            diagnostics.append(
                diagnostic(
                    "error",
                    "asset_size_mismatch",
                    f'asset "{path}" declares sizeBytes that does not match the stored object',
                    path=path,
                )
            )
    return diagnostics
