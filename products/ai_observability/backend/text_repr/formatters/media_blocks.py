import re

from posthog.dataclasses import frozen

_IMAGE_TYPES = frozenset({"image", "image_url", "input_image"})
_AUDIO_TYPES = frozenset({"audio", "input_audio"})
_FILE_TYPES = frozenset({"document", "file", "input_file"})
_GEMINI_DATA_KEYS = ("inline_data", "inlineData", "file_data", "fileData")
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


def parse_media_block(block: dict) -> MediaBlock | None:
    """Read an OpenAI chat or Responses, Anthropic, or Gemini media block. OTel parts get markers in `otel_parts`."""
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
        if block_type in _IMAGE_TYPES:
            return _image_block(block)
        if block_type in _AUDIO_TYPES:
            return MediaBlock(modality="audio")
        if block_type in _FILE_TYPES:
            return MediaBlock(modality="file")
    return None


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
    return _with_source("image", mime_type if isinstance(mime_type, str) else None, image_url or block.get("data"))


def _with_source(modality: str, mime_type: str | None, value: object) -> MediaBlock:
    if not isinstance(value, str) or not value or _REDACTED_RE.match(value):
        return MediaBlock(modality=modality, mime_type=mime_type)
    if value.startswith("data:") and ";base64," in value:
        header, payload = value[len("data:") :].split(";base64,", 1)
        return _with_source(modality, header or mime_type, payload)
    if value.startswith(_LINK_SCHEMES):
        return MediaBlock(modality=modality, mime_type=mime_type, url=value)
    return MediaBlock(modality=modality, mime_type=mime_type, base64_data=value)
