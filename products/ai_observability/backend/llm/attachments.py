import base64
from collections.abc import Callable
from dataclasses import field
from typing import Any, Literal

from posthog.dataclasses import frozen

IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
PDF_MIME_TYPE = "application/pdf"
# The formats OpenAI's chat API takes as input audio.
OPENAI_AUDIO_FORMATS = {"audio/wav": "wav", "audio/mpeg": "mp3"}
# Gemini reads these as well. The values are the `format` names OpenRouter's input_audio block takes.
AUDIO_FORMATS = {
    **OPENAI_AUDIO_FORMATS,
    "audio/aac": "aac",
    "audio/aiff": "aiff",
    "audio/flac": "flac",
    "audio/ogg": "ogg",
}
VIDEO_MIME_TYPES = frozenset({"video/mp4", "video/mpeg", "video/quicktime", "video/webm"})
# Providers whose image blocks take a link that they download themselves.
_URL_PROVIDERS = frozenset({"openai", "azure_openai", "anthropic", "gemini"})
# Providers that read PDFs natively.
_PDF_PROVIDERS = frozenset({"openai", "anthropic", "gemini"})
# Raw bytes per image. Anthropic allows 10 MB base64-encoded, about 7.5 MB raw, so keep a margin under it.
MAX_IMAGE_BYTES = {"anthropic": 7_000_000, "gemini": 15_000_000}
# Raw bytes per PDF for every provider. Each page costs about as many tokens as an image, and links have no other cap.
MAX_PDF_BYTES = 10_000_000
# Raw bytes per video. Gemini downloads links up to 15 MB, and inline bytes share the 15 MB request budget anyway.
MAX_VIDEO_BYTES = 15_000_000


@frozen
class AttachmentPart:
    """An image, PDF, audio clip or video in a message's content list. Each adapter converts it to its provider's block.

    Set `url` for a link the provider downloads, or `data` for inline bytes.
    """

    mime_type: str
    url: str | None = None
    data: bytes | None = field(default=None, repr=False)

    def base64(self) -> str:
        return base64.b64encode(self.data or b"").decode()

    def data_uri(self) -> str:
        return f"data:{self.mime_type};base64,{self.base64()}"

    @property
    def is_pdf(self) -> bool:
        return self.mime_type == PDF_MIME_TYPE

    @property
    def audio_format(self) -> str | None:
        return AUDIO_FORMATS.get(self.mime_type)


def attachment_transport(provider: str, model: str, mime_type: str) -> Literal["url", "inline"] | None:
    """How a provider accepts an attachment of this type: a link, inline base64, or not at all."""
    if provider == "openrouter":
        return _openrouter_transport(model, mime_type)
    openai_audio_model = provider == "openai" and "audio" in model
    if mime_type in AUDIO_FORMATS:
        # OpenAI takes audio only as inline base64, and only on its audio models, so audio always goes inline.
        reads_format = provider == "gemini" or (openai_audio_model and mime_type in OPENAI_AUDIO_FORMATS)
        return "inline" if reads_format else None
    if mime_type in VIDEO_MIME_TYPES:
        if provider != "gemini":
            return None
        # The Gemini 2.0 family can't fetch external links.
        return "inline" if model.startswith("gemini-2.0") else "url"
    if openai_audio_model:
        # OpenAI's audio models reject images and PDFs, and the rejection would drop the audio too.
        return None
    is_pdf = mime_type == PDF_MIME_TYPE
    if not is_pdf and mime_type not in IMAGE_MIME_TYPES:
        return None
    if is_pdf and provider not in _PDF_PROVIDERS:
        return None
    if provider == "gemini":
        if mime_type == "image/gif":
            return None
        # The Gemini 2.0 family can't fetch external links.
        return "inline" if model.startswith("gemini-2.0") else "url"
    if is_pdf and provider == "openai":
        # The chat API takes a PDF only as inline file data.
        return "inline"
    return "url" if provider in _URL_PROVIDERS else "inline"


def _openrouter_transport(model: str, mime_type: str) -> Literal["url", "inline"] | None:
    """OpenRouter routes many models, so its catalogue says what each one reads."""
    # Avoids a circular import: the OpenRouter adapter imports this module through the OpenAI one.
    from products.ai_observability.backend.llm.providers.openrouter import model_input_modalities  # noqa: PLC0415

    if mime_type in IMAGE_MIME_TYPES:
        modality = "image"
    elif mime_type == PDF_MIME_TYPE:
        # "file" means the model reads PDFs itself. Other models would get OpenRouter's paid OCR.
        modality = "file"
    elif mime_type in AUDIO_FORMATS:
        modality = "audio"
    elif mime_type in VIDEO_MIME_TYPES:
        modality = "video"
    else:
        return None
    modalities = model_input_modalities(model)
    if modalities is None:
        return "url" if modality == "image" else None
    if modality not in modalities:
        return None
    # Only Gemini models are known to read audio beyond WAV and MP3. A rejection would drop every attachment.
    if modality == "audio" and mime_type not in OPENAI_AUDIO_FORMATS and not model.startswith("google/"):
        return None
    # OpenRouter forwards a link only where the model's provider downloads it, and Gemini on AI Studio doesn't.
    return "url" if modality == "image" else "inline"


def max_videos(model: str) -> int:
    """Videos Gemini accepts in one request."""
    return 1 if model.removeprefix("google/").startswith(("gemini-1.", "gemini-2.0")) else 10


def convert_attachment_parts(
    messages: list[dict[str, Any]], convert: Callable[[AttachmentPart], Any]
) -> list[dict[str, Any]]:
    """Replace each AttachmentPart in the messages' content lists with the provider block that `convert` returns."""
    return [
        {
            **message,
            "content": [convert(part) if isinstance(part, AttachmentPart) else part for part in message["content"]],
        }
        if isinstance(message.get("content"), list)
        else message
        for message in messages
    ]
