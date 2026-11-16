import re
from collections.abc import Mapping

from ...facade import contracts
from .media_sources import has_redacted_media, is_renderable_media_source, parse_blob_pointer

_MEDIA_TYPE_BY_ITEM_TYPE: dict[str, contracts.TraceAttachmentMediaType] = {
    "image": "image",
    "image_url": "image",
    "input_image": "image",
    "audio": "audio",
    "input_audio": "audio",
    "video": "video",
    "file": "file",
    "document": "file",
    "input_file": "file",
}

# Providers nest the payload under one of these keys, each with its own field names.
_NESTED_PAYLOAD_KEYS = ("source", "file", "input_audio", "image_url", "inline_data", "inlineData")
_SOURCE_KEYS = ("url", "file_url", "image_url", "file_data", "image", "data", "file", "uri")
_MIME_KEYS = ("mediaType", "mimeType", "mime_type", "media_type")
_NAME_KEYS = ("filename", "name")

_URL_SCHEME = re.compile(r"[a-z][\w+.-]*:", re.IGNORECASE | re.ASCII)
_BASE64 = re.compile(r"[A-Za-z0-9+/=\s]+", re.ASCII)
_DATA_URI_MIME = re.compile(r"data:([^;,]+)", re.IGNORECASE)


def is_attachment_item_type(item_type: str) -> bool:
    return item_type in _MEDIA_TYPE_BY_ITEM_TYPE


def to_attachment(item: Mapping[str, object], team_id: int) -> contracts.TraceAttachmentPart:
    raw_type = item.get("type")
    item_type = raw_type if isinstance(raw_type, str) else ""
    nested = [value for key in _NESTED_PAYLOAD_KEYS if isinstance(value := item.get(key), dict)]
    containers = [*nested, item]
    source = _read_string(containers, _SOURCE_KEYS)
    mime_type = (
        _read_string(containers, _MIME_KEYS)
        or (_audio_format_mime(containers) if item_type == "input_audio" else None)
        or _source_mime(source)
    )
    media_type = _media_type(item_type, mime_type)
    is_known_media = is_attachment_item_type(item_type)
    # Matches the legacy player, which assumes WAV for raw audio sent without a mime type.
    payload_mime = mime_type or ("audio/wav" if media_type == "audio" else None)
    renderable = is_known_media and not has_redacted_media(item)
    return contracts.TraceAttachmentPart(
        kind="attachment",
        media_type=media_type,
        name=_read_string(containers, _NAME_KEYS) or (None if is_known_media else item_type),
        mime_type=mime_type,
        url=_resolve_url(source, payload_mime, team_id) if renderable else None,
    )


def _read_string(containers: list[Mapping[str, object]], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        for container in containers:
            value = container.get(key)
            if isinstance(value, str) and value != "":
                return value
    return None


def _audio_format_mime(containers: list[Mapping[str, object]]) -> str | None:
    audio_format = _read_string(containers, ("format",))
    return f"audio/{audio_format}" if audio_format else None


def _media_type(item_type: str, mime_type: str | None) -> contracts.TraceAttachmentMediaType:
    if not mime_type:
        return _MEDIA_TYPE_BY_ITEM_TYPE.get(item_type, "file")
    top_level = mime_type.split("/")[0]
    if top_level == "image":
        return "image"
    if top_level == "audio":
        return "audio"
    if top_level == "video":
        return "video"
    return "file"


def _source_mime(source: str | None) -> str | None:
    if source is None:
        return None
    if data_uri := _DATA_URI_MIME.match(source):
        return data_uri.group(1)
    pointer = parse_blob_pointer(source)
    return pointer.mime_type if pointer else None


def _resolve_url(source: str | None, mime_type: str | None, team_id: int) -> str | None:
    if source is None:
        return None
    if is_renderable_media_source(source):
        pointer = parse_blob_pointer(source)
        return f"/api/projects/{team_id}/ai_blob/v1/sha256/{pointer.sha256}" if pointer else source
    if _URL_SCHEME.match(source) or not mime_type or not _BASE64.fullmatch(source):
        return None
    return f"data:{mime_type};base64,{source}"
