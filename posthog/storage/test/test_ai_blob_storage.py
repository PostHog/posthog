from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.storage.ai_blob_storage import (
    AI_BLOB_RANGE_KEY,
    AI_BLOB_URL_KEY,
    is_s3_blob_url,
    parse_s3_url,
    transform_blob_properties,
    transform_s3_url_to_presigned,
)


class TestParseS3Url(SimpleTestCase):
    @parameterized.expand(
        [
            ("s3://bucket/key?range=0-100", ("bucket", "key", "0-100")),
            ("s3://ai-blobs/llma/phc_xxx/uuid?range=64-215", ("ai-blobs", "llma/phc_xxx/uuid", "64-215")),
            ("s3://my-bucket/path/to/file.json?range=1000-2000", ("my-bucket", "path/to/file.json", "1000-2000")),
            ("s3://bucket/key", ("bucket", "key", "")),
        ]
    )
    def test_parses_valid_s3_urls(self, url: str, expected: tuple[str, str, str]) -> None:
        result = parse_s3_url(url)
        assert result == expected

    @parameterized.expand(
        [
            ("https://bucket/key?range=0-100",),
            ("http://bucket/key",),
            ("not-a-url",),
            ("",),
        ]
    )
    def test_returns_none_for_invalid_urls(self, url: str) -> None:
        result = parse_s3_url(url)
        assert result is None


class TestIsS3BlobUrl(SimpleTestCase):
    @parameterized.expand(
        [
            ("s3://bucket/key", True),
            ("s3://bucket/key?range=0-100", True),
            ("https://bucket/key", False),
            ("not-a-url", False),
            (123, False),
            (None, False),
            ({"key": "value"}, False),
        ]
    )
    def test_correctly_identifies_s3_urls(self, value, expected: bool) -> None:
        result = is_s3_blob_url(value)
        assert result == expected


class TestTransformS3UrlToPresigned(SimpleTestCase):
    @patch("posthog.storage.ai_blob_storage._get_ai_s3_client")
    @override_settings(AI_S3_BUCKET="ai-blobs", AI_BLOB_PRESIGNED_TTL_SECONDS=3600)
    def test_transforms_s3_url_to_presigned(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value = "https://presigned-url.example.com"
        mock_get_client.return_value = mock_client

        result = transform_s3_url_to_presigned("s3://ai-blobs/llma/phc_xxx/uuid?range=64-215")

        assert result is not None
        assert result[AI_BLOB_URL_KEY] == "https://presigned-url.example.com"
        assert result[AI_BLOB_RANGE_KEY] == "64-215"

        mock_client.generate_presigned_url.assert_called_once_with(
            ClientMethod="get_object",
            Params={"Bucket": "ai-blobs", "Key": "llma/phc_xxx/uuid"},
            ExpiresIn=3600,
            HttpMethod="GET",
        )

    @override_settings(AI_S3_BUCKET=None)
    def test_returns_none_when_bucket_not_configured(self) -> None:
        result = transform_s3_url_to_presigned("s3://ai-blobs/key?range=0-100")
        assert result is None

    @patch("posthog.storage.ai_blob_storage._get_ai_s3_client")
    @override_settings(AI_S3_BUCKET="expected-bucket")
    def test_returns_none_for_bucket_mismatch(self, mock_get_client: MagicMock) -> None:
        result = transform_s3_url_to_presigned("s3://wrong-bucket/key?range=0-100")
        assert result is None
        mock_get_client.assert_not_called()

    @override_settings(AI_S3_BUCKET="ai-blobs")
    def test_returns_none_for_invalid_url(self) -> None:
        result = transform_s3_url_to_presigned("https://not-s3.example.com/key")
        assert result is None


class TestTransformBlobProperties(SimpleTestCase):
    @patch("posthog.storage.ai_blob_storage.transform_s3_url_to_presigned")
    @override_settings(AI_S3_BUCKET="bucket")
    def test_transforms_s3_urls_in_properties(self, mock_transform: MagicMock) -> None:
        mock_transform.return_value = {AI_BLOB_URL_KEY: "https://presigned", AI_BLOB_RANGE_KEY: "0-100"}

        properties = {
            "$ai_input": "s3://bucket/input?range=0-100",
            "$ai_output": "s3://bucket/output?range=100-200",
            "model": "gpt-4",
        }

        transform_blob_properties(properties)

        assert properties["$ai_input"] == {AI_BLOB_URL_KEY: "https://presigned", AI_BLOB_RANGE_KEY: "0-100"}
        assert properties["$ai_output"] == {AI_BLOB_URL_KEY: "https://presigned", AI_BLOB_RANGE_KEY: "0-100"}
        assert properties["model"] == "gpt-4"

    @patch("posthog.storage.ai_blob_storage.transform_s3_url_to_presigned")
    @override_settings(AI_S3_BUCKET="bucket")
    def test_leaves_non_s3_values_unchanged(self, mock_transform: MagicMock) -> None:
        properties = {
            "$ai_input": [{"role": "user", "content": "Hello"}],
            "model": "gpt-4",
            "temperature": 0.7,
        }

        transform_blob_properties(properties)

        mock_transform.assert_not_called()
        assert properties["$ai_input"] == [{"role": "user", "content": "Hello"}]

    @override_settings(AI_S3_BUCKET=None)
    def test_does_nothing_when_bucket_not_configured(self) -> None:
        properties = {"$ai_input": "s3://bucket/key?range=0-100"}
        transform_blob_properties(properties)
        assert properties["$ai_input"] == "s3://bucket/key?range=0-100"

    @patch("posthog.storage.ai_blob_storage.transform_s3_url_to_presigned")
    @override_settings(AI_S3_BUCKET="bucket")
    def test_keeps_original_value_on_transform_failure(self, mock_transform: MagicMock) -> None:
        mock_transform.return_value = None
        properties = {"$ai_input": "s3://bucket/key?range=0-100"}
        transform_blob_properties(properties)
        assert properties["$ai_input"] == "s3://bucket/key?range=0-100"
