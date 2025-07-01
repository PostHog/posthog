from unittest.mock import patch
from django.test import override_settings

from posthog.test.base import BaseTest
from posthog.hogql.database.schema.web_analytics_s3 import get_s3_url, get_s3_function_args


class TestWebAnalyticsS3(BaseTest):
    @override_settings(DEBUG=False)
    @patch(
        "posthog.settings.object_storage.OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET",
        "external-web-analytics-854902948032-us-east-1",
    )
    @patch("posthog.settings.object_storage.OBJECT_STORAGE_REGION", "us-east-1")
    def test_get_s3_url_production_format(self):
        table_name = "web_stats_daily_export"
        team_id = 2

        url = get_s3_url(table_name=table_name, team_id=team_id)

        expected_url = "https://external-web-analytics-854902948032-us-east-1.s3.us-east-1.amazonaws.com/web_stats_daily_export/2/data.native"

        assert url == expected_url

    @override_settings(DEBUG=False)
    @patch("posthog.settings.object_storage.OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET", "test-bucket-name")
    @patch("posthog.settings.object_storage.OBJECT_STORAGE_REGION", "eu-west-1")
    def test_get_s3_url_production_different_region(self):
        table_name = "web_bounces_daily_export"
        team_id = 123

        url = get_s3_url(table_name=table_name, team_id=team_id)

        expected_url = "https://test-bucket-name.s3.eu-west-1.amazonaws.com/web_bounces_daily_export/123/data.native"

        assert url == expected_url

    @override_settings(DEBUG=True)
    def test_get_s3_url_debug_format(self):
        table_name = "web_stats_daily_export"
        team_id = 2

        url = get_s3_url(table_name=table_name, team_id=team_id)

        expected_url = "http://objectstorage:19000/posthog/web_stats_daily_export/2/data.native"

        assert url == expected_url
        assert url.startswith("http://")  # HTTP protocol for local
        assert "objectstorage:19000" in url  # Local MinIO endpoint
        assert "/posthog/" in url  # Local bucket name

    def test_get_s3_url_path_validation(self):
        test_cases = [
            ("web_stats_daily_export", 1),
            ("web_bounces_daily_export", 999),
            ("test_export", 42),
        ]

        with (
            override_settings(DEBUG=False),
            patch("posthog.settings.object_storage.OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET", "test-bucket"),
            patch("posthog.settings.object_storage.OBJECT_STORAGE_REGION", "us-east-1"),
        ):
            for table_name, team_id in test_cases:
                url = get_s3_url(table_name=table_name, team_id=team_id)

                expected_path = f"/{table_name}/{team_id}/data.native"
                assert url.endswith(expected_path), f"Path structure incorrect for {table_name}"

    @override_settings(DEBUG=False)
    @patch("posthog.settings.object_storage.OBJECT_STORAGE_ACCESS_KEY_ID", "test-key")
    @patch("posthog.settings.object_storage.OBJECT_STORAGE_SECRET_ACCESS_KEY", "test-secret")
    def test_get_s3_function_args_production_should_not_include_credentials(self):
        s3_path = "https://test-bucket.s3.us-east-1.amazonaws.com/path/to/file.native"

        args = get_s3_function_args(s3_path)

        expected_args = "'https://test-bucket.s3.us-east-1.amazonaws.com/path/to/file.native', 'Native'"
        assert args == expected_args

    @override_settings(DEBUG=True)
    @patch("posthog.settings.object_storage.OBJECT_STORAGE_ACCESS_KEY_ID", "test-key")
    @patch("posthog.settings.object_storage.OBJECT_STORAGE_SECRET_ACCESS_KEY", "test-secret")
    def test_get_s3_function_args_debug(self):
        s3_path = "http://objectstorage:19000/posthog/path/to/file.native"

        args = get_s3_function_args(s3_path)

        expected_args = "'http://objectstorage:19000/posthog/path/to/file.native', 'test-key', 'test-secret', 'Native'"
        assert args == expected_args
