import json

from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from posthog.models.js_snippet_versioning import REDIS_POINTER_MAP_KEY, ManifestSyncError


class TestPublish(SimpleTestCase):
    def tearDown(self):
        cache.delete(REDIS_POINTER_MAP_KEY)

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.management.commands.js_snippet_version.validate_version_artifacts")
    @patch("posthog.management.commands.js_snippet_version.object_storage")
    def test_publishes_new_version(self, mock_storage, mock_validate):
        mock_validate.return_value = True
        mock_storage.read.return_value = None

        call_command("js_snippet_version", "publish", "1.359.0", "--accept")

        raw = cache.get(REDIS_POINTER_MAP_KEY)
        manifest = json.loads(raw)
        assert manifest["versions"] == ["1.359.0"]
        assert manifest["pointers"]["1"] == "1.359.0"
        assert manifest["pointers"]["1.359"] == "1.359.0"

        assert mock_storage.write.call_count == 2
        # First write: versions.json (raw entries)
        versions_call = mock_storage.write.call_args_list[0]
        written = json.loads(versions_call[0][1])
        assert len(written) == 1
        assert written[0]["version"] == "1.359.0"
        assert "timestamp" in written[0]
        # Second write: manifest.json (validated manifest backup)
        manifest_call = mock_storage.write.call_args_list[1]
        backup = json.loads(manifest_call[0][1])
        assert backup["pointers"]["1"] == "1.359.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.management.commands.js_snippet_version.validate_version_artifacts")
    @patch("posthog.management.commands.js_snippet_version.object_storage")
    def test_publish_appends_to_existing_manifest(self, mock_storage, mock_validate):
        mock_validate.return_value = True
        existing = [{"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"}]
        mock_storage.read.return_value = json.dumps(existing)

        call_command("js_snippet_version", "publish", "1.359.0", "--accept")

        # First write is versions.json
        written = json.loads(mock_storage.write.call_args_list[0][0][1])
        assert len(written) == 2
        assert written[0]["version"] == "1.358.0"
        assert written[1]["version"] == "1.359.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.management.commands.js_snippet_version.validate_version_artifacts")
    def test_publish_fails_when_artifacts_missing(self, mock_validate):
        mock_validate.return_value = False

        with self.assertRaises(CommandError) as ctx:
            call_command("js_snippet_version", "publish", "99.99.99")

        assert "artifacts" in str(ctx.exception).lower()

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.management.commands.js_snippet_version.validate_version_artifacts")
    @patch("posthog.management.commands.js_snippet_version.object_storage")
    def test_publish_fails_for_duplicate_version(self, mock_storage, mock_validate):
        mock_validate.return_value = True
        existing = [{"version": "1.359.0", "timestamp": "2025-01-15T00:00:00Z"}]
        mock_storage.read.return_value = json.dumps(existing)

        with self.assertRaises(CommandError) as ctx:
            call_command("js_snippet_version", "publish", "1.359.0")

        assert "already exists" in str(ctx.exception).lower()

    @override_settings(POSTHOG_JS_S3_BUCKET="")
    def test_publish_fails_when_bucket_not_configured(self):
        with self.assertRaises(CommandError) as ctx:
            call_command("js_snippet_version", "publish", "1.359.0")

        assert "POSTHOG_JS_S3_BUCKET" in str(ctx.exception)

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.remote_config.RemoteConfig.purge_cdn_by_tag")
    @patch("posthog.management.commands.js_snippet_version.validate_version_artifacts")
    @patch("posthog.management.commands.js_snippet_version.object_storage")
    def test_publish_purges_affected_pins(self, mock_storage, mock_validate, mock_purge):
        mock_validate.return_value = True
        existing = [{"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"}]
        mock_storage.read.return_value = json.dumps(existing)

        call_command("js_snippet_version", "publish", "1.359.0", "--accept", "--purge")

        purged_tags = {call.args[0] for call in mock_purge.call_args_list}
        assert "posthog-js-1" in purged_tags
        assert "posthog-js-1.359" in purged_tags
        assert "posthog-js-1.358" not in purged_tags

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.remote_config.RemoteConfig.purge_cdn_by_tag")
    @patch("posthog.management.commands.js_snippet_version.validate_version_artifacts")
    @patch("posthog.management.commands.js_snippet_version.object_storage")
    def test_publish_without_purge_flag_does_not_purge(self, mock_storage, mock_validate, mock_purge):
        mock_validate.return_value = True
        mock_storage.read.return_value = None

        call_command("js_snippet_version", "publish", "1.359.0", "--accept")

        mock_purge.assert_not_called()

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.management.commands.js_snippet_version.validate_version_artifacts")
    @patch("posthog.management.commands.js_snippet_version.object_storage")
    def test_publish_dry_run_does_not_write(self, mock_storage, mock_validate):
        mock_validate.return_value = True
        mock_storage.read.return_value = None

        call_command("js_snippet_version", "publish", "1.359.0")

        mock_storage.write.assert_not_called()
        assert cache.get(REDIS_POINTER_MAP_KEY) is None


class TestYank(SimpleTestCase):
    def tearDown(self):
        cache.delete(REDIS_POINTER_MAP_KEY)

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.management.commands.js_snippet_version.object_storage")
    def test_yanks_version(self, mock_storage):
        existing = [
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
            {"version": "1.359.0", "timestamp": "2025-01-20T00:00:00Z"},
        ]
        mock_storage.read.return_value = json.dumps(existing)

        call_command("js_snippet_version", "yank", "1.359.0", "--accept")

        # First write is versions.json
        written = json.loads(mock_storage.write.call_args_list[0][0][1])
        assert written[1]["yanked"] is True
        assert "yanked" not in written[0]

        raw = cache.get(REDIS_POINTER_MAP_KEY)
        manifest = json.loads(raw)
        assert manifest["pointers"]["1"] == "1.358.0"
        assert "1.359" not in manifest["pointers"]
        assert "1.359.0" not in manifest["versions"]
        assert "1.358.0" in manifest["versions"]

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.management.commands.js_snippet_version.object_storage")
    def test_yank_fails_when_version_not_found(self, mock_storage):
        mock_storage.read.return_value = json.dumps([])

        with self.assertRaises(CommandError) as ctx:
            call_command("js_snippet_version", "yank", "1.359.0")

        assert "not found" in str(ctx.exception).lower()

    @override_settings(POSTHOG_JS_S3_BUCKET="")
    def test_yank_fails_when_bucket_not_configured(self):
        with self.assertRaises(CommandError) as ctx:
            call_command("js_snippet_version", "yank", "1.359.0")

        assert "POSTHOG_JS_S3_BUCKET" in str(ctx.exception)

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.remote_config.RemoteConfig.purge_cdn_by_tag")
    @patch("posthog.management.commands.js_snippet_version.object_storage")
    def test_yank_purges_affected_pins(self, mock_storage, mock_purge):
        existing = [
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
            {"version": "1.359.0", "timestamp": "2025-01-20T00:00:00Z"},
        ]
        mock_storage.read.return_value = json.dumps(existing)

        call_command("js_snippet_version", "yank", "1.359.0", "--accept", "--purge")

        purged_tags = {call.args[0] for call in mock_purge.call_args_list}
        assert "posthog-js-1" in purged_tags
        assert "posthog-js-1.359" in purged_tags
        assert "posthog-js-1.358" not in purged_tags

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.management.commands.js_snippet_version.object_storage")
    def test_yank_dry_run_does_not_write(self, mock_storage):
        existing = [
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
            {"version": "1.359.0", "timestamp": "2025-01-20T00:00:00Z"},
        ]
        mock_storage.read.return_value = json.dumps(existing)

        call_command("js_snippet_version", "yank", "1.359.0")

        mock_storage.write.assert_not_called()
        assert cache.get(REDIS_POINTER_MAP_KEY) is None


class TestSync(SimpleTestCase):
    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.management.commands.js_snippet_version.sync_manifest_from_s3")
    def test_sync_runs_successfully(self, mock_sync):
        mock_sync.return_value = {"versions": ["1.358.0"], "pointers": {"1": "1.358.0"}}
        call_command("js_snippet_version", "sync")
        mock_sync.assert_called_once()

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.management.commands.js_snippet_version.sync_manifest_from_s3")
    def test_sync_raises_command_error_on_manifest_sync_error(self, mock_sync):
        mock_sync.side_effect = ManifestSyncError("versions.json not found in S3")
        with self.assertRaises(CommandError) as ctx:
            call_command("js_snippet_version", "sync")
        assert "versions.json not found in S3" in str(ctx.exception)
