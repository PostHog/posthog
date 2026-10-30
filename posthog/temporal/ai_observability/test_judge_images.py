import base64

import pytest
from unittest.mock import patch

from posthog.storage.object_storage import ObjectStorageError
from posthog.temporal.ai_observability.judge_images import MAX_IMAGES, JudgeImages

from products.ai_observability.backend.llm.images import ImagePart
from products.ai_observability.backend.text_repr.formatters.media_blocks import MediaBlock, parse_media_block

OBJECT_STORAGE = "products.ai_observability.backend.ai_blobs.object_storage"


def _pointer(digit: str, mime: str = "image%2Fjpeg") -> MediaBlock:
    return MediaBlock(modality="image", url=f"phaiblob://v1/sha256/{digit * 64}?mime={mime}&size=63357")


def _inline(digit: str, length: int = 4) -> MediaBlock:
    return MediaBlock(modality="image", mime_type="image/png", base64_data=digit * length)


class TestJudgeImagesMarkers:
    def test_numbers_images_and_reuses_the_number_for_a_repeat(self):
        images = JudgeImages(team_id=7)
        inline = MediaBlock(modality="image", mime_type="image/png", base64_data="aGk=")

        markers = [images.marker(media) for media in (_pointer("a"), inline, _pointer("a"))]

        assert markers == ["[image 1]", "[image 2]", "[image 1]"]

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
        assert JudgeImages(team_id=7).marker(media) == marker


class TestJudgeImagesContent:
    def test_an_image_referenced_again_at_the_end_stays_attached(self):
        images = JudgeImages(team_id=7)
        markers = [images.marker(_inline(f"{i:02}")) for i in range(MAX_IMAGES + 1)]
        # The output repeats the first input image after every newer one.
        content = images.content(" ".join([*markers, markers[0]]), "openai", "gpt-5.5")

        assert {"type": "text", "text": "Image 1:"} in content
        assert {"type": "text", "text": "Image 2:"} not in content
        assert {"type": "text", "text": "Images not attached, over the judge's image limit: 1."} in content

    def test_attaches_the_newest_images_when_over_the_limit(self):
        images = JudgeImages(team_id=7)
        prompt = " ".join(images.marker(_inline(f"{i:02}")) for i in range(MAX_IMAGES + 1))

        content = images.content(prompt, "openai", "gpt-5.5")

        assert content[1] == {"type": "text", "text": "Image 2:"}
        assert content[-4:-1] == [
            {"type": "text", "text": f"Image {MAX_IMAGES + 1}:"},
            ImagePart(mime_type="image/png", data=base64.b64decode(f"{MAX_IMAGES:02}" * 4)),
            {"type": "text", "text": "Images not attached, over the judge's image limit: 1."},
        ]

    @pytest.mark.parametrize(
        ("provider", "model", "expected_image"),
        [
            pytest.param("openai", "gpt-5.5", ImagePart(mime_type="image/jpeg", url="https://signed"), id="link"),
            pytest.param("together_ai", "any", ImagePart(mime_type="image/jpeg", data=b"hi"), id="inline"),
            pytest.param("gemini", "gemini-2.0-flash", ImagePart(mime_type="image/jpeg", data=b"hi"), id="gemini_2_0"),
        ],
    )
    def test_attaches_each_image_under_its_label(self, provider: str, model: str, expected_image: ImagePart):
        images = JudgeImages(team_id=7)
        prompt = f"Input: user: {images.marker(_pointer('a', mime='image%2FJPG'))} What does this chart show?"

        with (
            patch(f"{OBJECT_STORAGE}.get_presigned_url", return_value="https://signed") as presign,
            patch(f"{OBJECT_STORAGE}.head_object_strict", return_value={"ContentLength": 2}),
            patch(f"{OBJECT_STORAGE}.read_bytes", return_value=b"hi") as read,
        ):
            content = images.content(prompt, provider, model)

        assert content == [
            {"type": "text", "text": "The transcript refers to these images as [image N]."},
            {"type": "text", "text": "Image 1:"},
            expected_image,
            {"type": "text", "text": prompt},
        ]
        storage_call = presign if expected_image.url else read
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
                "gemini", "gemini-3-flash", _pointer("a", mime="image%2Fgif"), None, id="format_rejected_by_provider"
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
        images = JudgeImages(team_id=7)
        prompt = f"user: {images.marker(media)}"

        with (
            patch(f"{OBJECT_STORAGE}.get_presigned_url", return_value=None),
            patch(f"{OBJECT_STORAGE}.head_object_strict", return_value=None, side_effect=storage_error),
        ):
            content = images.content(prompt, provider, model)

        assert content[1] == {"type": "text", "text": "Image 1: could not be attached."}

    def test_stops_calling_storage_after_a_storage_error(self):
        images = JudgeImages(team_id=7)
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
        images = JudgeImages(team_id=7)
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

    def test_skips_images_whose_marker_was_sampled_out_of_the_prompt(self):
        images = JudgeImages(team_id=7)
        images.marker(_pointer("a"))

        assert images.content("user: hello", "openai", "gpt-5.5") == "user: hello"
