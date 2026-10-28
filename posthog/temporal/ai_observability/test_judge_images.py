import pytest
from unittest.mock import patch

from posthog.temporal.ai_observability.judge_images import MAX_IMAGES, OVER_LIMIT_MARKER, JudgeImages

from products.ai_observability.backend.llm.types import ImagePart
from products.ai_observability.backend.text_repr.formatters.media_blocks import MediaBlock

OBJECT_STORAGE = "products.ai_observability.backend.ai_blobs.object_storage"


def _pointer(digit: str, mime: str = "image%2Fjpeg", size: int = 63357) -> MediaBlock:
    return MediaBlock(modality="image", url=f"phaiblob://v1/sha256/{digit * 64}?mime={mime}&size={size}")


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
                MediaBlock(modality="image", url="https://example.com/a"),
                "[image: https://example.com/a]",
                id="link_without_type",
            ),
            pytest.param(_pointer("a", size=4_000_000), OVER_LIMIT_MARKER, id="too_large"),
        ],
    )
    def test_images_it_cannot_attach_keep_an_unnumbered_marker(self, media: MediaBlock, marker: str):
        assert JudgeImages(team_id=7).marker(media) == marker

    def test_stops_attaching_at_the_image_limit(self):
        images = JudgeImages(team_id=7)
        markers = [
            images.marker(MediaBlock(modality="image", mime_type="image/png", base64_data=f"image{i}"))
            for i in range(MAX_IMAGES + 1)
        ]

        assert markers[-2:] == [f"[image {MAX_IMAGES}]", OVER_LIMIT_MARKER]


class TestJudgeImagesContent:
    @pytest.mark.parametrize(
        ("provider", "model", "expected_image"),
        [
            pytest.param("openai", "gpt-5.5", ImagePart(mime_type="image/jpeg", url="https://signed"), id="link"),
            pytest.param("together_ai", "any", ImagePart(mime_type="image/jpeg", base64_data="aGk="), id="inline"),
            pytest.param(
                "gemini", "gemini-2.0-flash", ImagePart(mime_type="image/jpeg", base64_data="aGk="), id="gemini_2_0"
            ),
        ],
    )
    def test_attaches_each_image_under_its_label(self, provider: str, model: str, expected_image: ImagePart):
        images = JudgeImages(team_id=7)
        prompt = f"Input: user: {images.marker(_pointer('a'))} What does this chart show?"

        with (
            patch(f"{OBJECT_STORAGE}.get_presigned_url", return_value="https://signed") as presign,
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
        ("provider", "model", "media"),
        [
            pytest.param("openai", "gpt-5.5", _pointer("a"), id="blob_missing"),
            pytest.param(
                "gemini", "gemini-3-flash", _pointer("a", mime="image%2Fgif"), id="format_rejected_by_provider"
            ),
            pytest.param(
                "together_ai",
                "any",
                MediaBlock(modality="image", mime_type="image/png", url="https://example.com/a.png"),
                id="customer_link_without_link_support",
            ),
        ],
    )
    def test_reports_an_image_it_could_not_attach(self, provider: str, model: str, media: MediaBlock):
        images = JudgeImages(team_id=7)
        prompt = f"user: {images.marker(media)}"

        with patch(f"{OBJECT_STORAGE}.get_presigned_url", return_value=None):
            content = images.content(prompt, provider, model)

        assert content[1] == {"type": "text", "text": "Image 1: could not be attached."}

    def test_skips_images_whose_marker_was_sampled_out_of_the_prompt(self):
        images = JudgeImages(team_id=7)
        images.marker(_pointer("a"))

        assert images.content("user: hello", "openai", "gpt-5.5") == "user: hello"
