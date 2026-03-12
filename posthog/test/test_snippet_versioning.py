import json

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

import posthog.models.snippet_versioning as sv
from posthog.models.snippet_versioning import (
    REDIS_JS_KEY_PREFIX,
    REDIS_POINTER_MAP_KEY,
    compute_pointer_map,
    get_js_content,
    resolve_version,
    validate_version_artifacts,
)
from posthog.tasks.snippet_versioning import _LAST_HASH_REDIS_KEY, sync_posthog_js_versions


class TestComputePointerMap(SimpleTestCase):
    def test_empty_entries(self):
        assert compute_pointer_map([]) == {}

    def test_single_version(self):
        entries = [{"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"}]
        result = compute_pointer_map(entries)
        assert result == {"1": "1.358.0", "1.358": "1.358.0"}

    def test_multiple_versions_picks_highest(self):
        entries = [
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
            {"version": "1.358.3", "timestamp": "2025-01-16T00:00:00Z"},
            {"version": "1.359.0", "timestamp": "2025-01-20T00:00:00Z"},
        ]
        result = compute_pointer_map(entries)
        assert result == {"1": "1.359.0", "1.358": "1.358.3", "1.359": "1.359.0"}

    def test_yanked_versions_excluded(self):
        entries = [
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
            {"version": "1.359.0", "timestamp": "2025-01-20T00:00:00Z", "yanked": True},
        ]
        result = compute_pointer_map(entries)
        assert result == {"1": "1.358.0", "1.358": "1.358.0"}

    def test_all_yanked_returns_empty(self):
        entries = [
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z", "yanked": True},
        ]
        assert compute_pointer_map(entries) == {}

    def test_order_independent(self):
        entries = [
            {"version": "1.359.0", "timestamp": "2025-01-20T00:00:00Z"},
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
        ]
        result = compute_pointer_map(entries)
        assert result["1"] == "1.359.0"

    def test_yanked_false_not_excluded(self):
        entries = [
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z", "yanked": False},
        ]
        result = compute_pointer_map(entries)
        assert result == {"1": "1.358.0", "1.358": "1.358.0"}


class TestGetJsContent(SimpleTestCase):
    @override_settings(POSTHOG_JS_S3_BUCKET="")
    def test_returns_disk_content_when_versioning_disabled(self):
        content = get_js_content("1.358.0")
        assert content is not None
        assert len(content) > 0

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_returns_redis_content_when_cached(self):
        cache.set(f"{REDIS_JS_KEY_PREFIX}:1.358.0", "cached-js-content", 3600)
        try:
            content = get_js_content("1.358.0")
            assert content == "cached-js-content"
        finally:
            cache.delete(f"{REDIS_JS_KEY_PREFIX}:1.358.0")

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.snippet_versioning.object_storage.read")
    def test_fetches_from_s3_and_caches_in_redis(self, mock_read):
        mock_read.return_value = "s3-js-content"
        try:
            content = get_js_content("1.358.0")
            assert content == "s3-js-content"
            mock_read.assert_called_once_with("posthog-js/v1.358.0/array.js", bucket="test-bucket", missing_ok=True)
            assert cache.get(f"{REDIS_JS_KEY_PREFIX}:1.358.0") == "s3-js-content"
        finally:
            cache.delete(f"{REDIS_JS_KEY_PREFIX}:1.358.0")

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.snippet_versioning.object_storage.read")
    def test_falls_back_to_disk_when_s3_misses(self, mock_read):
        mock_read.return_value = None
        content = get_js_content("99.99.99")
        assert content is not None
        assert len(content) > 0


class TestValidateArtifacts(SimpleTestCase):
    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.snippet_versioning.object_storage.read")
    def test_returns_true_when_array_js_exists(self, mock_read):
        mock_read.return_value = "js-content"
        assert validate_version_artifacts("1.358.0") is True
        mock_read.assert_called_once_with("posthog-js/v1.358.0/array.js", bucket="test-bucket", missing_ok=True)

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.snippet_versioning.object_storage.read")
    def test_returns_false_when_array_js_missing(self, mock_read):
        mock_read.return_value = None
        assert validate_version_artifacts("99.99.99") is False


class TestResolveVersion(SimpleTestCase):
    def setUp(self):
        sv._pointer_map_cache = None
        sv._pointer_map_cache_time = 0
        pointers = {"1": "1.359.0", "1.358": "1.358.3"}
        cache.set(REDIS_POINTER_MAP_KEY, json.dumps(pointers))

    def tearDown(self):
        cache.delete(REDIS_POINTER_MAP_KEY)
        sv._pointer_map_cache = None
        sv._pointer_map_cache_time = 0

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_exact_version_returned_as_is(self):
        assert resolve_version("1.358.0") == "1.358.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_major_pin_resolved_via_pointers(self):
        assert resolve_version("1") == "1.359.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_minor_pin_resolved_via_pointers(self):
        assert resolve_version("1.358") == "1.358.3"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_none_defaults_to_major_pin(self):
        assert resolve_version(None) == "1.359.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="")
    def test_returns_none_when_versioning_disabled(self):
        assert resolve_version(None) is None


class TestSyncTask(SimpleTestCase):
    def setUp(self):
        sv._pointer_map_cache = None
        sv._pointer_map_cache_time = 0

    def tearDown(self):
        cache.delete(REDIS_POINTER_MAP_KEY)
        cache.delete(_LAST_HASH_REDIS_KEY)
        sv._pointer_map_cache = None
        sv._pointer_map_cache_time = 0

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.tasks.snippet_versioning.validate_version_artifacts")
    @patch("posthog.tasks.snippet_versioning.object_storage.read")
    def test_syncs_versions_json_to_redis(self, mock_read, mock_validate):
        manifest = [
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
            {"version": "1.359.0", "timestamp": "2025-01-20T00:00:00Z"},
        ]
        mock_read.return_value = json.dumps(manifest)
        mock_validate.return_value = True

        sync_posthog_js_versions()

        raw = cache.get(REDIS_POINTER_MAP_KEY)
        pointers = json.loads(raw)
        assert pointers["1"] == "1.359.0"
        assert pointers["1.358"] == "1.358.0"
        assert pointers["1.359"] == "1.359.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.tasks.snippet_versioning.validate_version_artifacts")
    @patch("posthog.tasks.snippet_versioning.object_storage.read")
    def test_skips_update_when_unchanged(self, mock_read, mock_validate):
        manifest = json.dumps([{"version": "1.359.0", "timestamp": "2025-01-20T00:00:00Z"}])
        mock_read.return_value = manifest
        mock_validate.return_value = True

        # First sync
        sync_posthog_js_versions()
        # Second sync with same content
        sync_posthog_js_versions()

        mock_validate.assert_called_once()

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.tasks.snippet_versioning.validate_version_artifacts")
    @patch("posthog.tasks.snippet_versioning.object_storage.read")
    def test_rejects_update_when_artifacts_missing(self, mock_read, mock_validate):
        manifest = [{"version": "99.99.99", "timestamp": "2025-01-20T00:00:00Z"}]
        mock_read.return_value = json.dumps(manifest)
        mock_validate.return_value = False

        sync_posthog_js_versions()

        assert cache.get(REDIS_POINTER_MAP_KEY) is None

    @override_settings(POSTHOG_JS_S3_BUCKET="")
    def test_noop_when_versioning_disabled(self):
        sync_posthog_js_versions()
        assert cache.get(REDIS_POINTER_MAP_KEY) is None
