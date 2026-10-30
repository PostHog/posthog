import base64

import pytest
from unittest.mock import patch

from posthog.storage.object_storage import ObjectStorageError
from posthog.temporal.ai_observability.judge_attachments import MAX_ATTACHMENTS, JudgeAttachments

from products.ai_observability.backend.llm.attachments import MAX_IMAGE_BYTES, MAX_PDF_BYTES, AttachmentPart
from products.ai_observability.backend.text_repr.formatters.media_blocks import MediaBlock, parse_media_block

OBJECT_STORAGE = "products.ai_observability.backend.ai_blobs.object_storage"


def _pointer(digit: str, mime: str = "image%2Fjpeg") -> MediaBlock:
    modality = "audio" if mime.startswith("audio") else "image"
    return MediaBlock(modality=modality, url=f"phaiblob://v1/sha256/{digit * 64}?mime={mime}&size=63357")


def _inline(digit: str, length: int = 4) -> MediaBlock:
    return MediaBlock(modality="image", mime_type="image/png", base64_data=digit * length)


class TestJudgeAttachmentsMarkers:
    def test_numbers_each_kind_and_reuses_the_number_for_a_repeat(self):
        images = JudgeAttachments(team_id=7)
        inline = MediaBlock(modality="image", mime_type="image/png", base64_data="aGk=")

        pdf = _pointer("b", mime="application%2Fpdf")

        markers = [images.marker(media) for media in (_pointer("a"), pdf, inline, _pointer("a"))]

        assert markers == ["[image 1]", "[file 1]", "[image 2]", "[image 1]"]

    @pytest.mark.parametrize(
        ("media", "marker"),
        [
            pytest.param(MediaBlock(modality="audio", base64_data="aGk="), "[audio]", id="not_an_image"),
            pytest.param(_pointer("a", mime="image%2Fsvg%2Bxml"), "[image]", id="unsupported_format"),
            pytest.param(
                MediaBlock(modality="image", mime_type="image/png", url="https://example.com/a.png"),
                "[image: https://example.com/a.png]",
                id="customer_link",
            ),
            pytest.param(
                parse_media_block({"file_data": {"mime_type": "image/png", "file_uri": "gs://bucket/a.png"}}),
                "[image]",
                id="gemini_cloud_storage_uri",
            ),
        ],
    )
    def test_images_it_cannot_attach_keep_an_unnumbered_marker(self, media: MediaBlock, marker: str):
        assert JudgeAttachments(team_id=7).marker(media) == marker


class TestJudgeAttachmentsContent:
    def test_an_image_referenced_again_at_the_end_stays_attached(self):
        images = JudgeAttachments(team_id=7)
        markers = [images.marker(_inline(f"{i:02}")) for i in range(MAX_ATTACHMENTS + 1)]
        # The output repeats the first input image after every newer one.
        content = images.content(" ".join([*markers, markers[0]]), "openai", "gpt-5.5")

        assert {"type": "text", "text": "Image 1:"} in content
        assert {"type": "text", "text": "Image 2:"} not in content
        assert {"type": "text", "text": "Not attached, over the judge's attachment limit: 1."} in content

    def test_attaches_the_newest_images_when_over_the_limit(self):
        images = JudgeAttachments(team_id=7)
        prompt = " ".join(images.marker(_inline(f"{i:02}")) for i in range(MAX_ATTACHMENTS + 1))

        content = images.content(prompt, "openai", "gpt-5.5")

        assert content[1] == {"type": "text", "text": "Image 2:"}
        assert content[-4:-1] == [
            {"type": "text", "text": f"Image {MAX_ATTACHMENTS + 1}:"},
            AttachmentPart(mime_type="image/png", data=base64.b64decode(f"{MAX_ATTACHMENTS:02}" * 4)),
            {"type": "text", "text": "Not attached, over the judge's attachment limit: 1."},
        ]

    @pytest.mark.parametrize(
        ("provider", "model", "mime", "expected_label", "expected_part"),
        [
            pytest.param(
                "openai",
                "gpt-5.5",
                "image%2FJPG",
                "Image 1:",
                AttachmentPart(mime_type="image/jpeg", url="https://signed"),
                id="link",
            ),
            pytest.param(
                "together_ai",
                "any",
                "image%2FJPG",
                "Image 1:",
                AttachmentPart(mime_type="image/jpeg", data=b"hi"),
                id="inline",
            ),
            pytest.param(
                "gemini",
                "gemini-2.0-flash",
                "image%2FJPG",
                "Image 1:",
                AttachmentPart(mime_type="image/jpeg", data=b"hi"),
                id="gemini_2_0",
            ),
            pytest.param(
                "anthropic",
                "claude-haiku-4-5",
                "application%2Fpdf",
                "File 1:",
                AttachmentPart(mime_type="application/pdf", url="https://signed"),
                id="pdf_link",
            ),
            pytest.param(
                "openai",
                "gpt-5.5",
                "application%2Fpdf",
                "File 1:",
                AttachmentPart(mime_type="application/pdf", data=b"hi"),
                id="pdf_inline_on_openai",
            ),
            pytest.param(
                "gemini",
                "gemini-3-flash",
                "image%2Fgif",
                "Not attached, this judge can't read their file type: 1.",
                None,
                id="format_rejected_by_provider",
            ),
            pytest.param(
                "gemini",
                "gemini-2.5-flash",
                "audio%2Fwav",
                "Audio 1:",
                AttachmentPart(mime_type="audio/wav", data=b"hi"),
                id="audio_inline_on_gemini",
            ),
            pytest.param(
                "openai",
                "gpt-4o-audio-preview",
                "audio%2Fmp3",
                "Audio 1:",
                AttachmentPart(mime_type="audio/mpeg", data=b"hi"),
                id="audio_on_an_openai_audio_model",
            ),
            pytest.param(
                "openai",
                "gpt-5.5",
                "audio%2Fwav",
                "Not attached, this judge can't read their file type: 1.",
                None,
                id="audio_on_an_openai_model_without_audio_input",
            ),
            pytest.param(
                "openai",
                "gpt-4o-audio-preview",
                "image%2Fpng",
                "Not attached, this judge can't read their file type: 1.",
                None,
                id="image_on_an_openai_audio_model",
            ),
            pytest.param(
                "openrouter",
                "any",
                "application%2Fpdf",
                "Not attached, this judge can't read their file type: 1.",
                None,
                id="pdf_unsupported_provider",
            ),
        ],
    )
    def test_attaches_each_attachment_under_its_label(
        self, provider: str, model: str, mime: str, expected_label: str, expected_part: AttachmentPart | None
    ):
        images = JudgeAttachments(team_id=7)
        prompt = f"Input: user: {images.marker(_pointer('a', mime=mime))} What does this chart show?"

        with (
            patch(f"{OBJECT_STORAGE}.get_presigned_url", return_value="https://signed") as presign,
            patch(f"{OBJECT_STORAGE}.head_object_strict", return_value={"ContentLength": 2}),
            patch(f"{OBJECT_STORAGE}.read_bytes", return_value=b"hi") as read,
        ):
            content = images.content(prompt, provider, model)

        assert content == [
            {"type": "text", "text": "The transcript refers to these attachments as [image N], [file N] or [audio N]."},
            {"type": "text", "text": expected_label},
            *([expected_part] if expected_part else []),
            {"type": "text", "text": prompt},
        ]
        if expected_part:
            storage_call = presign if expected_part.url else read
            assert storage_call.call_args.args[0] == f"aio/7/sha256/{'a' * 64}"

    @pytest.mark.parametrize(
        ("provider", "model", "media", "storage_error"),
        [
            pytest.param("openai", "gpt-5.5", _pointer("a"), None, id="blob_missing_for_a_link"),
            pytest.param("together_ai", "any", _pointer("a"), None, id="blob_missing_for_inline"),
            pytest.param(
                "together_ai", "any", _pointer("a"), ObjectStorageError("head_object failed"), id="storage_error"
            ),
            pytest.param(
                "gemini",
                "gemini-3-flash",
                MediaBlock(modality="image", mime_type="image/png", base64_data="aGk"),
                None,
                id="invalid_inline_base64",
            ),
            pytest.param(
                "gemini",
                "gemini-3-flash",
                MediaBlock(modality="image", mime_type="image/png", base64_data="aGk\u00e9"),
                None,
                id="non_ascii_inline_base64",
            ),
        ],
    )
    def test_reports_an_image_it_could_not_attach(
        self, provider: str, model: str, media: MediaBlock, storage_error: Exception | None
    ):
        images = JudgeAttachments(team_id=7)
        prompt = f"user: {images.marker(media)}"

        with (
            patch(f"{OBJECT_STORAGE}.get_presigned_url", return_value=None),
            patch(f"{OBJECT_STORAGE}.head_object_strict", return_value=None, side_effect=storage_error),
        ):
            content = images.content(prompt, provider, model)

        assert content[1] == {"type": "text", "text": "Image 1: could not be attached."}

    def test_stops_calling_storage_after_a_storage_error(self):
        images = JudgeAttachments(team_id=7)
        prompt = f"user: {images.marker(_pointer('a'))} {images.marker(_pointer('b'))}"

        with patch(f"{OBJECT_STORAGE}.head_object_strict", side_effect=ObjectStorageError("timed out")) as head:
            content = images.content(prompt, "together_ai", "any")

        assert head.call_count == 1
        assert {"type": "text", "text": "Image 1: could not be attached."} in content
        assert {"type": "text", "text": "Image 2: could not be attached."} in content

    @pytest.mark.parametrize(
        ("provider", "media", "too_large", "reads"),
        [
            pytest.param("openai", _pointer, set(), 0, id="links_have_no_byte_cap"),
            pytest.param("anthropic", _pointer, {1, 2}, 0, id="provider_limit_on_links"),
            # The pointers claim 63 KB, so this also checks that the budget uses the stored size.
            pytest.param("together_ai", _pointer, {1}, 1, id="stored_size_for_inline_providers"),
            pytest.param(
                "openai", lambda digit: _inline(digit, length=13_400_000), {1}, 0, id="inline_images_on_link_providers"
            ),
        ],
    )
    def test_caps_image_bytes(self, provider: str, media, too_large: set[int], reads: int):
        images = JudgeAttachments(team_id=7)
        prompt = f"user: {images.marker(media('a'))} {images.marker(media('b'))}"

        with (
            patch(f"{OBJECT_STORAGE}.get_presigned_url", return_value="https://signed"),
            patch(f"{OBJECT_STORAGE}.head_object_strict", return_value={"ContentLength": 10_000_000}),
            patch(f"{OBJECT_STORAGE}.read_bytes", return_value=b"x" * 10_000_000) as read,
        ):
            content = images.content(prompt, provider, "any")

        assert {
            number
            for number in (1, 2)
            if {"type": "text", "text": f"Image {number}: not attached, too large."} in content
        } == too_large
        # An image over the budget is never downloaded.
        assert read.call_count == reads

    def test_caps_pdf_bytes_on_links(self):
        images = JudgeAttachments(team_id=7)
        prompt = f"user: {images.marker(_pointer('a', mime='application%2Fpdf'))}"

        with (
            patch(f"{OBJECT_STORAGE}.get_presigned_url", return_value="https://signed") as presign,
            patch(f"{OBJECT_STORAGE}.head_object_strict", return_value={"ContentLength": MAX_PDF_BYTES + 1}),
        ):
            # Gemini has no image byte limit, so only the PDF cap can reject this one.
            content = images.content(prompt, "gemini", "gemini-3-flash")

        assert {"type": "text", "text": "File 1: not attached, too large."} in content
        presign.assert_not_called()

    def test_attachments_the_judge_cannot_read_take_no_slot(self):
        images = JudgeAttachments(team_id=7)
        image = images.marker(_inline("aa"))
        pdfs = " ".join(
            images.marker(MediaBlock(modality="file", url=f"phaiblob://v1/sha256/{i:064x}?mime=application%2Fpdf"))
            for i in range(MAX_ATTACHMENTS)
        )

        content = images.content(f"user: {image} {pdfs}", "openrouter", "openai/gpt-5-mini")

        assert content[1:4] == [
            {"type": "text", "text": "Image 1:"},
            AttachmentPart(mime_type="image/png", data=base64.b64decode("aa" * 4)),
            {"type": "text", "text": f"Not attached, this judge can't read their file type: {MAX_ATTACHMENTS}."},
        ]

    def test_an_inline_image_exactly_at_the_provider_limit_is_attached(self):
        images = JudgeAttachments(team_id=7)
        encoded = base64.b64encode(b"x" * MAX_IMAGE_BYTES["anthropic"]).decode()
        prompt = f"user: {images.marker(MediaBlock(modality='image', mime_type='image/png', base64_data=encoded))}"

        content = images.content(prompt, "anthropic", "claude-haiku-4-5")

        assert content[1] == {"type": "text", "text": "Image 1:"}

    def test_skips_images_whose_marker_was_sampled_out_of_the_prompt(self):
        images = JudgeAttachments(team_id=7)
        images.marker(_pointer("a"))

        assert images.content("user: hello", "openai", "gpt-5.5") == "user: hello"
