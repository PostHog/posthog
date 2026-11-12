import time

from parameterized import parameterized

from products.ai_observability.backend.facade import contracts
from products.ai_observability.backend.logic.traces.attachments import is_attachment_item_type, to_attachment

BLOB_HASH = "a" * 64
REDACTED_IMAGE = "[base64 image redacted]"


def attachment(
    media_type: contracts.TraceAttachmentMediaType,
    *,
    name: str | None = None,
    mime_type: str | None = None,
    url: str | None = None,
) -> contracts.TraceAttachmentPart:
    return contracts.TraceAttachmentPart(
        kind="attachment", media_type=media_type, name=name, mime_type=mime_type, url=url
    )


@parameterized.expand(
    [
        (
            "openai_image_url",
            {"type": "image_url", "image_url": {"url": "https://cdn.example.com/receipt.png"}},
            attachment("image", url="https://cdn.example.com/receipt.png"),
        ),
        (
            "openai_input_audio_raw_base64",
            {"type": "input_audio", "input_audio": {"data": "UklGRg==", "format": "wav"}},
            attachment("audio", mime_type="audio/wav", url="data:audio/wav;base64,UklGRg=="),
        ),
        (
            "openai_file_with_filename",
            {"type": "file", "file": {"file_data": "data:application/pdf;base64,JVBERi0=", "filename": "quote.pdf"}},
            attachment(
                "file", name="quote.pdf", mime_type="application/pdf", url="data:application/pdf;base64,JVBERi0="
            ),
        ),
        (
            "anthropic_base64_image",
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0="}},
            attachment("image", mime_type="image/png", url="data:image/png;base64,iVBORw0="),
        ),
        (
            "anthropic_document",
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBERi0="}},
            attachment("file", mime_type="application/pdf", url="data:application/pdf;base64,JVBERi0="),
        ),
        (
            "vercel_file_part_with_image_mime_type",
            {"type": "file", "mediaType": "image/jpeg", "file": "https://cdn.example.com/latte.jpg"},
            attachment("image", mime_type="image/jpeg", url="https://cdn.example.com/latte.jpg"),
        ),
        (
            "file_part_with_unresolvable_upload_reference",
            {"type": "file", "mediaType": "image/png", "file": "upload://screen-01"},
            attachment("image", mime_type="image/png"),
        ),
        (
            "gemini_audio_blob_pointer",
            {"type": "audio", "mime_type": "audio/wav", "data": f"phaiblob://v1/sha256/{BLOB_HASH}?mime=audio/wav"},
            attachment("audio", mime_type="audio/wav", url=f"/api/projects/7/ai_blob/v1/sha256/{BLOB_HASH}"),
        ),
        (
            "gemini_inline_data_image",
            {"type": "image", "inline_data": {"mime_type": "image/webp", "data": "UklGRg=="}},
            attachment("image", mime_type="image/webp", url="data:image/webp;base64,UklGRg=="),
        ),
        (
            "gemini_inline_data_document_sent_as_image",
            {"type": "image", "inlineData": {"mimeType": "application/pdf", "data": "JVBERi0="}},
            attachment("file", mime_type="application/pdf", url="data:application/pdf;base64,JVBERi0="),
        ),
        (
            "gemini_interactions_image_with_top_level_data",
            {"type": "image", "data": "iVBORw0=", "mime_type": "image/png"},
            attachment("image", mime_type="image/png", url="data:image/png;base64,iVBORw0="),
        ),
        (
            "gemini_interactions_image_with_https_uri",
            {"type": "image", "uri": "https://cdn.example.com/image.png"},
            attachment("image", url="https://cdn.example.com/image.png"),
        ),
        (
            "gemini_interactions_image_with_offloaded_blob_uri",
            {"type": "image", "uri": f"phaiblob://v1/sha256/{BLOB_HASH}?mime=image/png"},
            attachment("image", mime_type="image/png", url=f"/api/projects/7/ai_blob/v1/sha256/{BLOB_HASH}"),
        ),
        (
            "gemini_interactions_image_with_redacted_data_and_uri",
            {
                "type": "image",
                "data": "[base64 image/png redacted]",
                "mime_type": "image/png",
                "uri": "https://cdn.example.com/image.png",
            },
            attachment("image", mime_type="image/png"),
        ),
        (
            "gemini_interactions_image_with_redacted_data_no_mime_and_uri",
            {"type": "image", "data": REDACTED_IMAGE, "uri": "https://cdn.example.com/image.png"},
            attachment("image"),
        ),
        (
            "image_with_redacted_payload_and_sibling_url",
            {"type": "image", "inlineData": {"data": REDACTED_IMAGE, "url": "https://example.com/hidden.png"}},
            attachment("image"),
        ),
        (
            "legacy_image_whose_nested_redaction_suppresses_a_competing_uri",
            {
                "type": "image",
                "uri": "https://example.com/hidden.png",
                "content": {"image": "https://example.com/hidden.png", "inlineData": {"data": REDACTED_IMAGE}},
            },
            attachment("image"),
        ),
        (
            "image_whose_payload_the_sdk_redacted",
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": REDACTED_IMAGE}},
            attachment("image", mime_type="image/png"),
        ),
        (
            "blob_pointer_wrapped_in_a_data_uri",
            {"type": "image", "data": f"data:image/png;base64,phaiblob://v1/sha256/{BLOB_HASH}"},
            attachment("image", mime_type="image/png", url=f"/api/projects/7/ai_blob/v1/sha256/{BLOB_HASH}"),
        ),
    ]
)
def test_maps_provider_shapes(_name: str, item: dict[str, object], expected: contracts.TraceAttachmentPart) -> None:
    assert to_attachment(item, 7) == expected


def test_blob_url_uses_the_reading_team() -> None:
    item = {"type": "image", "uri": f"phaiblob://v1/sha256/{BLOB_HASH}?mime=image/png"}

    assert to_attachment(item, 7).url == f"/api/projects/7/ai_blob/v1/sha256/{BLOB_HASH}"


def test_a_source_full_of_data_uri_starts_is_checked_in_linear_time() -> None:
    item = {"type": "image_url", "image_url": {"url": "data:" * 200_000}}
    started = time.monotonic()

    to_attachment(item, 7)

    assert time.monotonic() - started < 1


@parameterized.expand(
    [("image_url", True), ("input_file", True), ("video", True), ("text", False), ("tool_use", False)]
)
def test_recognises_attachment_item_types(item_type: str, expected: bool) -> None:
    assert is_attachment_item_type(item_type) is expected
