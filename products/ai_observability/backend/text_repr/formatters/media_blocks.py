from posthog.dataclasses import frozen

_IMAGE_TYPES = frozenset({"image", "image_url", "input_image"})
_AUDIO_TYPES = frozenset({"audio", "input_audio"})
_FILE_TYPES = frozenset({"document", "file", "input_file"})
_GEMINI_DATA_KEYS = ("inline_data", "inlineData", "file_data", "fileData")
_LINK_SCHEMES = ("https://", "http://", "phaiblob://")


@frozen
class MediaBlock:
    """An image, audio, video or file content block, and where its bytes are.

    `url` holds an https link or a `phaiblob://` pointer, `base64_data` holds inline bytes.
    """

    modality: str
    mime_type: str | None = None
    url: str | None = None
    base64_data: str | None = None

    @property
    def web_url(self) -> str | None:
        return self.url if self.url is not None and self.url.startswith(("https://", "http://")) else None

    def marker(self) -> str:
        # A web link can tell the judge what the media shows. Base64 and pointers are token noise.
        return f"[{self.modality}: {self.web_url}]" if self.web_url else f"[{self.modality}]"


def parse_media_block(block: dict) -> MediaBlock | None:
    """Read an OpenAI chat or Responses, Anthropic, or Gemini media block. OTel parts get markers in `otel_parts`."""
    block_type = block.get("type")
    if isinstance(block_type, str):
        if block_type in _IMAGE_TYPES:
            return _image_block(block)
        if block_type in _AUDIO_TYPES:
            return MediaBlock(modality="audio")
        if block_type in _FILE_TYPES:
            return MediaBlock(modality="file")
    for key in _GEMINI_DATA_KEYS:
        data = block.get(key)
        if isinstance(data, dict):
            mime_type = data.get("mime_type") or data.get("mimeType")
            mime_type = mime_type if isinstance(mime_type, str) else None
            modality = mime_type.split("/")[0] if mime_type else ""
            if modality not in ("image", "audio", "video"):
                modality = "file"
            return _with_source(modality, mime_type, data.get("data") or data.get("file_uri") or data.get("fileUri"))
    return None


def media_block_marker(block: dict) -> str | None:
    media = parse_media_block(block)
    return media.marker() if media is not None else None


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
    return _with_source("image", None, image_url)


def _with_source(modality: str, mime_type: str | None, value: object) -> MediaBlock:
    if not isinstance(value, str) or not value:
        return MediaBlock(modality=modality, mime_type=mime_type)
    if value.startswith("data:") and ";base64," in value:
        header, payload = value[len("data:") :].split(";base64,", 1)
        return _with_source(modality, header or mime_type, payload)
    if value.startswith(_LINK_SCHEMES):
        return MediaBlock(modality=modality, mime_type=mime_type, url=value)
    return MediaBlock(modality=modality, mime_type=mime_type, base64_data=value)
