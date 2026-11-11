import re
from collections.abc import Callable
from dataclasses import replace

from posthog.dataclasses import frozen

_IMAGE_TYPES = frozenset({"image", "image_url", "input_image"})
_AUDIO_TYPES = frozenset({"audio", "input_audio"})
_FILE_TYPES = frozenset({"document", "file", "input_file"})
_GEMINI_DATA_KEYS = ("inline_data", "inlineData", "file_data", "fileData")
_OTEL_TYPES = frozenset({"blob", "uri"})
_GENERIC_MIME_TYPE = "application/octet-stream"
_MIME_KEYS = ("mediaType", "mimeType", "mime_type", "media_type")
_FILE_SOURCE_KEYS = ("file_data", "file_url", "data", "uri", "url")
_LINK_SCHEMES = ("https://", "http://", "phaiblob://")
# Without full capture the SDKs replace the bytes with a placeholder such as `[base64 image redacted]`.
# Same pattern as the frontend's `isRedactedMediaSentinel`.
_REDACTED_RE = re.compile(r"^\s*\[base64\b[^\]]*\bredacted\]\s*$", re.IGNORECASE)


@frozen
class MediaBlock:
    """An image, audio, video or file content block, and where its bytes are.

    `url` holds an https link or a `phaiblob://` pointer, `base64_data` holds inline bytes.
    """

    modality: str
    mime_type: str | None = None
    url: str | None = None
    base64_data: str | None = None

    def marker(self) -> str:
        # A web link can tell the judge what the media shows. Base64 and pointers are token noise.
        if self.url is not None and self.url.startswith(("https://", "http://")):
            return f"[{self.modality}: {self.url}]"
        return f"[{self.modality}]"


# Turns a media block into the text a transcript shows in its place, for example `[image 1]`.
MediaMarker = Callable[[MediaBlock], str]


def parse_media_block(block: dict) -> MediaBlock | None:
    """Read an OpenAI chat or Responses, Anthropic, Gemini, or OTel GenAI media block."""
    # Before the `type` check: the PostHog Gemini SDK records `{"type": "image", "inline_data": {...}}`.
    for key in _GEMINI_DATA_KEYS:
        data = block.get(key)
        if isinstance(data, dict):
            mime_type = data.get("mime_type") or data.get("mimeType")
            mime_type = mime_type if isinstance(mime_type, str) else None
            modality = mime_type.split("/")[0] if mime_type else ""
            if modality not in ("image", "audio", "video"):
                modality = "file"
            uri = data.get("file_uri") or data.get("fileUri")
            if isinstance(uri, str):
                # A file URI is never inline bytes, and a `gs://` URI is not a link anyone else can fetch.
                return MediaBlock(
                    modality=modality, mime_type=mime_type, url=uri if uri.startswith(_LINK_SCHEMES) else None
                )
            return _with_source(modality, mime_type, data.get("data"))
    block_type = block.get("type")
    if isinstance(block_type, str):
        if block_type in _OTEL_TYPES:
            return _otel_part(block)
        if block_type in _IMAGE_TYPES:
            return _image_block(block)
        if block_type in _AUDIO_TYPES:
            return _audio_block(block)
        if block_type in _FILE_TYPES:
            return _file_block(block)
    return None


def _otel_part(part: dict) -> MediaBlock:
    mime_type = part.get("mime_type")
    mime_type = mime_type if isinstance(mime_type, str) else None
    modality = part.get("modality")
    if not isinstance(modality, str) or not modality:
        modality = mime_type.split("/")[0] if mime_type else "media"
    if part["type"] == "blob":
        return _with_source(modality, mime_type, part.get("content"))
    uri = part.get("uri")
    # A `uri` part never holds inline bytes, and a `gs://` URI is not a link anyone else can fetch.
    return MediaBlock(
        modality=modality,
        mime_type=mime_type,
        url=uri if isinstance(uri, str) and uri.startswith(_LINK_SCHEMES) else None,
    )


def _image_block(block: dict) -> MediaBlock:
    image_url = block.get("image_url")
    if isinstance(image_url, dict):
        image_url = image_url.get("url")
    source = block.get("source")
    if isinstance(source, dict):
        media_type = source.get("media_type")
        return _with_source(
            "image", media_type if isinstance(media_type, str) else None, source.get("data") or source.get("url")
        )
    # The Gemini Interactions API puts `data` and `mime_type` on the block itself.
    mime_type = block.get("mime_type") or block.get("mimeType")
    return _with_source(
        "image", mime_type if isinstance(mime_type, str) else None, image_url or block.get("data") or block.get("uri")
    )


def _audio_block(block: dict) -> MediaBlock:
    # OpenAI chat names the format instead of a MIME type: `{"input_audio": {"data": ..., "format": "wav"}}`.
    audio = block.get("input_audio")
    if isinstance(audio, dict):
        audio_format = audio.get("format")
        mime_type = f"audio/{audio_format}" if isinstance(audio_format, str) and audio_format else None
        return _with_source("audio", mime_type, audio.get("data"))
    source = block.get("source")
    fields = source if isinstance(source, dict) else block
    mime_type = next((fields[key] for key in _MIME_KEYS if isinstance(fields.get(key), str)), None)
    value = next((fields[key] for key in _FILE_SOURCE_KEYS if fields.get(key)), None)
    return _with_source("audio", mime_type, value)


def _file_block(block: dict) -> MediaBlock:
    source = block.get("source")
    if isinstance(source, dict):
        # Anthropic document.
        mime_type, value = source.get("media_type"), source.get("data") or source.get("url")
        filename = None
    else:
        file = block.get("file")
        # OpenAI chat nests the file, and the Responses API, Gemini and the Vercel AI SDK put it on the block.
        # Vercel records `{"type": "file", "mediaType": ..., "file": <data>}`.
        fields = file if isinstance(file, dict) else block
        mime_type = next((block[key] for key in _MIME_KEYS if isinstance(block.get(key), str)), None)
        value = next((fields[key] for key in _FILE_SOURCE_KEYS if fields.get(key)), None)
        if value is None and isinstance(file, str):
            value = file
        filename = fields.get("filename")
    media = _with_source("file", mime_type if isinstance(mime_type, str) else None, value)
    if media.mime_type is None and isinstance(filename, str) and filename.lower().endswith(".pdf"):
        media = replace(media, mime_type="application/pdf")
    # The Vercel AI SDK sends images, audio and video as file parts too.
    modality = media.mime_type.split("/")[0] if media.mime_type else ""
    return replace(media, modality=modality) if modality in ("image", "audio", "video") else media


def _with_source(modality: str, mime_type: str | None, value: object) -> MediaBlock:
    if not isinstance(value, str) or not value:
        return MediaBlock(modality=modality, mime_type=mime_type)
    if value.startswith("data:") and ";base64," in value:
        # Unwrap one envelope only. Its payload is bytes or a wrapped pointer, never another data URI,
        # and unwrapping nested prefixes would copy the payload once per level.
        header, value = value[len("data:") :].split(";base64,", 1)
        # A declared type beats a generic one in the data URI, as in the trace view.
        if header and (mime_type is None or mime_type.strip().lower() == _GENERIC_MIME_TYPE):
            mime_type = header
    if _REDACTED_RE.match(value) or value.startswith("data:"):
        return MediaBlock(modality=modality, mime_type=mime_type)
    if value.startswith(_LINK_SCHEMES):
        return MediaBlock(modality=modality, mime_type=mime_type, url=value)
    # Base64 never holds a space, so a value with one is an SDK placeholder such as `raw files not supported`.
    if " " in value:
        return MediaBlock(modality=modality, mime_type=mime_type)
    return MediaBlock(modality=modality, mime_type=mime_type, base64_data=value)
