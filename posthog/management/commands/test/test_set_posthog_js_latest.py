import json

from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from posthog.models.snippet_versioning import REDIS_LATEST_KEY


class TestSetPosthogJsLatest(SimpleTestCase):
    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.management.commands.set_posthog_js_latest.validate_version_artifacts")
    @patch("posthog.management.commands.set_posthog_js_latest.object_storage")
    def test_sets_latest_version(self, mock_storage, mock_validate):
        mock_validate.return_value = True
        mock_storage.read.return_value = json.dumps({"latest": "1.358.0"})

        call_command("set_posthog_js_latest", "1.359.0")

        # Verify Redis was updated
        raw = cache.get(REDIS_LATEST_KEY)
        pointers = json.loads(raw)
        assert pointers["latest"] == "1.359.0"

        # Verify S3 was updated
        mock_storage.write.assert_called_once()
        cache.delete(REDIS_LATEST_KEY)

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.management.commands.set_posthog_js_latest.validate_version_artifacts")
    def test_fails_when_artifacts_missing(self, mock_validate):
        mock_validate.return_value = False

        with self.assertRaises(CommandError) as ctx:
            call_command("set_posthog_js_latest", "99.99.99")

        assert "artifacts" in str(ctx.exception).lower()

    @override_settings(POSTHOG_JS_S3_BUCKET="")
    def test_fails_when_bucket_not_configured(self):
        with self.assertRaises(CommandError) as ctx:
            call_command("set_posthog_js_latest", "1.359.0")

        assert "POSTHOG_JS_S3_BUCKET" in str(ctx.exception)
