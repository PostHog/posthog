import re
from collections.abc import Mapping

from posthog.dataclasses import frozen

from ...ai_blobs import BlobPointer

# Without full AI capture the SDKs drop the payload and leave a marker whose wording varies per SDK
# and media type, so the shape is matched rather than a fixed set of strings.
_SENTINEL = re.compile(r"\s*\[base64\b[^\]]*\bredacted\]\s*", re.IGNORECASE | re.ASCII)
# Deliberately loose: recipes build this prefix by template, so the mime can be absent or carry extra
# parameters. A stricter pattern would let a wrapped sentinel through as a renderable source.
_BASE64_DATA_URI_PREFIX = re.compile(r"data:[^,]*;base64,", re.IGNORECASE)
_DATA_URI_WRAPPED_POINTER = re.compile(r"data:[\w.+-]+/[\w.+-]+;base64,(phaiblob://.*)", re.ASCII)
_PAYLOAD_KEYS = ("inline_data", "inlineData", "source")


@frozen
class _GeminiInlineData:
    data: str
    mime_type: str


def is_redacted_media_sentinel(value: str) -> bool:
    # Only a leading prefix is stripped, as in the browser. Searching the whole string for it is quadratic in the
    # number of `data:` occurrences, which event content controls.
    prefix = _BASE64_DATA_URI_PREFIX.match(value)
    return _SENTINEL.fullmatch(value[prefix.end() :] if prefix else value) is not None


def parse_blob_pointer(value: str) -> BlobPointer | None:
    wrapped = _DATA_URI_WRAPPED_POINTER.fullmatch(value)
    return BlobPointer.parse(wrapped.group(1) if wrapped else value)


def is_renderable_media_source(value: str) -> bool:
    if is_redacted_media_sentinel(value):
        return False
    lowered = value.lower()
    return lowered.startswith(("data:", "http://", "https://")) or parse_blob_pointer(value) is not None


def has_redacted_media(item: Mapping[str, object]) -> bool:
    """Only explicit SDK redaction markers imply that media was not captured."""
    item_type = item.get("type")
    if item_type == "image":
        # Legacy messages wrap one image payload in `content`; only that level is inspected.
        content = item.get("content")
        legacy = {**content, "type": "image"} if isinstance(content, dict) else None
        if any(_image_is_redacted(image) for image in (item, legacy) if image is not None):
            return True
        if _is_base64_source(item):
            return _is_sentinel(_mapping(item["source"]).get("data"))
        return is_gemini_document(item) and _has_redacted_payload_data(item)
    if item_type == "input_image" and isinstance(item.get("image_url"), str):
        return _is_sentinel(item["image_url"])
    if item_type == "image_url":
        return _is_sentinel(_mapping(item.get("image_url")).get("url"))
    if item_type == "document":
        if _is_base64_source(item):
            return _is_sentinel(_mapping(item["source"]).get("data"))
        return is_gemini_document(item) and _has_redacted_payload_data(item)
    if item_type == "file":
        return _is_sentinel(_mapping(item.get("file")).get("file_data"))
    if item_type == "audio":
        return _is_sentinel(item.get("data"))
    return False


def is_gemini_document(item: Mapping[str, object]) -> bool:
    inline = _gemini_inline_data(item)
    if inline is None:
        return False
    item_type = item.get("type")
    return item_type == "document" or (item_type == "image" and not inline.mime_type.startswith("image/"))


def _image_is_redacted(image: Mapping[str, object]) -> bool:
    uri = image.get("uri")
    payload_redacted = _has_redacted_payload_data(image) or _is_sentinel(uri)
    return (not is_gemini_document(image) and payload_redacted) or _is_sentinel(image.get("image"))


def _has_redacted_payload_data(item: Mapping[str, object]) -> bool:
    payloads = [item, *(item.get(key) for key in _PAYLOAD_KEYS)]
    return any(isinstance(p, dict) and _is_sentinel(p.get("data")) for p in payloads)


def _gemini_inline_data(item: Mapping[str, object]) -> _GeminiInlineData | None:
    candidates = [
        (item.get("inline_data"), ("mime_type", "mimeType")),
        (item.get("inlineData"), ("mimeType", "mime_type")),
        (item, ("mime_type", "mimeType")),
    ]
    for payload, mime_keys in candidates:
        if not isinstance(payload, dict):
            continue
        mime_type = next((payload[key] for key in mime_keys if payload.get(key) is not None), None)
        if isinstance(payload.get("data"), str) and isinstance(mime_type, str):
            return _GeminiInlineData(data=payload["data"], mime_type=mime_type)
    return None


def _is_base64_source(item: Mapping[str, object]) -> bool:
    source = item.get("source")
    return (
        isinstance(source, dict)
        and source.get("type") == "base64"
        and isinstance(source.get("data"), str)
        and isinstance(source.get("media_type"), str)
    )


def _is_sentinel(value: object) -> bool:
    return isinstance(value, str) and is_redacted_media_sentinel(value)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}
