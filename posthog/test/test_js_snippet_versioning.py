import json

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

import posthog.models.js_snippet_versioning as sv
from posthog.models.js_snippet_versioning import (
    REDIS_JS_KEY_PREFIX,
    REDIS_POINTER_MAP_KEY,
    VersionEntry,
    changed_pointers,
    compute_version_manifest,
    get_js_content,
    resolve_version,
    sync_manifest_from_s3,
    validate_version_artifacts,
)
from posthog.tasks.js_snippet_versioning import sync_js_snippet_manifest


def _make_manifest(versions: list[str], pointers: dict[str, str]) -> dict:
    return {"versions": versions, "pointers": pointers}


def _reset_caches():
    sv._cached_manifest = None
    sv._js_content_cache.clear()


class TestComputeVersionManifest(SimpleTestCase):
    def test_empty_entries(self):
        result = compute_version_manifest([])
        assert result == {"versions": [], "pointers": {}}

    def test_single_version(self):
        entries: list[VersionEntry] = [{"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"}]
        result = compute_version_manifest(entries)
        assert result == {
            "versions": ["1.358.0"],
            "pointers": {"1": "1.358.0", "1.358": "1.358.0"},
        }

    def test_multiple_versions_picks_highest(self):
        entries: list[VersionEntry] = [
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
            {"version": "1.358.3", "timestamp": "2025-01-16T00:00:00Z"},
            {"version": "1.359.0", "timestamp": "2025-01-20T00:00:00Z"},
        ]
        result = compute_version_manifest(entries)
        assert result["versions"] == ["1.358.0", "1.358.3", "1.359.0"]
        assert result["pointers"] == {"1": "1.359.0", "1.358": "1.358.3", "1.359": "1.359.0"}

    def test_yanked_versions_excluded(self):
        entries: list[VersionEntry] = [
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
            {"version": "1.359.0", "timestamp": "2025-01-20T00:00:00Z", "yanked": True},
        ]
        result = compute_version_manifest(entries)
        assert result == {
            "versions": ["1.358.0"],
            "pointers": {"1": "1.358.0", "1.358": "1.358.0"},
        }

    def test_all_yanked_returns_empty(self):
        entries: list[VersionEntry] = [
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z", "yanked": True},
        ]
        assert compute_version_manifest(entries) == {"versions": [], "pointers": {}}

    def test_order_independent(self):
        entries: list[VersionEntry] = [
            {"version": "1.359.0", "timestamp": "2025-01-20T00:00:00Z"},
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
        ]
        result = compute_version_manifest(entries)
        assert result["pointers"]["1"] == "1.359.0"

    def test_yanked_false_not_excluded(self):
        entries: list[VersionEntry] = [
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z", "yanked": False},
        ]
        result = compute_version_manifest(entries)
        assert result == {
            "versions": ["1.358.0"],
            "pointers": {"1": "1.358.0", "1.358": "1.358.0"},
        }

    def test_prerelease_versions_included_but_not_in_pointers(self):
        entries: list[VersionEntry] = [
            {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
            {"version": "1.359.0-beta.1", "timestamp": "2025-01-20T00:00:00Z"},
        ]
        result = compute_version_manifest(entries)
        assert "1.359.0-beta.1" in result["versions"]
        assert result["pointers"]["1"] == "1.358.0"

    def test_prerelease_does_not_override_stable_pointer(self):
        entries: list[VersionEntry] = [
            {"version": "1.360.0", "timestamp": "2025-01-15T00:00:00Z"},
            {"version": "1.361.0-dev", "timestamp": "2025-01-20T00:00:00Z"},
        ]
        result = compute_version_manifest(entries)
        assert result["pointers"]["1"] == "1.360.0"
        assert "1.361" not in result["pointers"]


class TestGetJsContent(SimpleTestCase):
    def setUp(self):
        _reset_caches()
        manifest = _make_manifest(
            versions=["1.358.0"],
            pointers={"1": "1.358.0", "1.358": "1.358.0"},
        )
        cache.set(REDIS_POINTER_MAP_KEY, json.dumps(manifest))
        self._disk_patcher = patch(
            "posthog.models.js_snippet_versioning._get_disk_js_content", return_value="mock-disk-js-content"
        )
        self._disk_patcher.start()

    def tearDown(self):
        self._disk_patcher.stop()
        cache.delete(REDIS_POINTER_MAP_KEY)
        _reset_caches()

    @override_settings(POSTHOG_JS_S3_BUCKET="")
    def test_returns_disk_content_when_versioning_disabled(self):
        content = get_js_content("1.358.0")
        assert content is not None
        assert len(content) > 0

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_returns_disk_content_when_version_not_resolved(self):
        content = get_js_content(None)
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
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_fetches_from_s3_and_caches_in_redis(self, mock_read):
        mock_read.return_value = "s3-js-content"
        try:
            content = get_js_content("1.358.0")
            assert content == "s3-js-content"
            mock_read.assert_called_once_with("static/1.358.0/array.js", missing_ok=True)
            assert cache.get(f"{REDIS_JS_KEY_PREFIX}:1.358.0") == "s3-js-content"
        finally:
            cache.delete(f"{REDIS_JS_KEY_PREFIX}:1.358.0")

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_falls_back_to_disk_when_s3_misses(self, mock_read):
        mock_read.return_value = None
        content = get_js_content("1.358.0")
        assert content is not None
        assert len(content) > 0

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_returns_disk_for_unknown_exact_version(self):
        content = get_js_content("99.99.99")
        assert content is not None
        assert len(content) > 0

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_falls_back_to_disk_on_s3_exception(self, mock_read):
        from posthog.storage.object_storage import ObjectStorageError

        mock_read.side_effect = ObjectStorageError("S3 connection failed")
        content = get_js_content("1.358.0")
        assert content is not None
        assert len(content) > 0

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_rejects_invalid_resolved_version(self):
        content = get_js_content("../../../etc/passwd")
        assert content is not None
        assert len(content) > 0  # falls back to disk


class TestValidateArtifacts(SimpleTestCase):
    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_head")
    def test_returns_true_when_array_js_exists(self, mock_head):
        mock_head.return_value = True
        assert validate_version_artifacts("1.358.0") is True
        mock_head.assert_called_once_with("static/1.358.0/array.js")

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_head")
    def test_returns_false_when_array_js_missing(self, mock_head):
        mock_head.return_value = False
        assert validate_version_artifacts("99.99.99") is False

    @override_settings(POSTHOG_JS_S3_BUCKET="")
    def test_returns_false_when_bucket_not_configured(self):
        assert validate_version_artifacts("1.358.0") is False


class TestResolveVersion(SimpleTestCase):
    def setUp(self):
        _reset_caches()
        manifest = _make_manifest(
            versions=["1.358.3", "1.359.0"],
            pointers={"1": "1.359.0", "1.358": "1.358.3", "1.359": "1.359.0"},
        )
        cache.set(REDIS_POINTER_MAP_KEY, json.dumps(manifest))

    def tearDown(self):
        cache.delete(REDIS_POINTER_MAP_KEY)
        _reset_caches()

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_exact_known_version_returned_as_is(self):
        assert resolve_version("1.359.0") == "1.359.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_exact_unknown_version_returns_none(self):
        assert resolve_version("99.99.99") is None

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

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_yanked_exact_version_falls_back_to_minor_pointer(self):
        # 1.358.0 is not in manifest.versions (simulating a yank),
        # but the minor pointer 1.358 -> 1.358.3 still exists
        assert resolve_version("1.358.0") == "1.358.3"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_missing_minor_pointer_falls_back_to_major(self):
        # 1.500.0 is unknown and there's no 1.500 pointer, but 1 -> 1.359.0
        assert resolve_version("1.500.0") == "1.359.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_missing_minor_series_falls_back_to_major(self):
        # 1.500 has no pointer, but 1 -> 1.359.0
        assert resolve_version("1.500") == "1.359.0"


class TestGetManifestResilience(SimpleTestCase):
    def setUp(self):
        _reset_caches()

    def tearDown(self):
        cache.delete(REDIS_POINTER_MAP_KEY)
        _reset_caches()

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_read", return_value=None)
    def test_negative_caches_missing_manifest(self, _mock_s3):
        # No manifest in Redis or S3 — first call should try both, second should not
        with patch("posthog.models.js_snippet_versioning.cache") as mock_cache:
            mock_cache.get.return_value = None
            mock_cache.set = lambda *a, **kw: None
            assert resolve_version("1") is None
            assert resolve_version("1") is None
            # Only one Redis call despite two resolve_version calls
            assert mock_cache.get.call_count == 1

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_read", return_value=None)
    def test_negative_cache_expires(self, _mock_s3):
        with patch("posthog.models.js_snippet_versioning.cache") as mock_cache:
            mock_cache.get.return_value = None
            mock_cache.set = lambda *a, **kw: None
            assert resolve_version("1") is None

            # Expire the negative cache
            sv._cached_manifest.cached_at = 0  # type: ignore

            assert resolve_version("1") is None
            assert mock_cache.get.call_count == 2

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_read", return_value=None)
    def test_redis_connection_error_returns_none(self, _mock_s3):
        with patch("posthog.models.js_snippet_versioning.cache") as mock_cache:
            mock_cache.get.side_effect = ConnectionError("Redis unavailable")
            mock_cache.set = lambda *a, **kw: None
            assert resolve_version("1") is None

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_read", return_value=None)
    def test_redis_connection_error_is_negative_cached(self, _mock_s3):
        with patch("posthog.models.js_snippet_versioning.cache") as mock_cache:
            mock_cache.get.side_effect = ConnectionError("Redis unavailable")
            mock_cache.set = lambda *a, **kw: None
            assert resolve_version("1") is None
            assert resolve_version("1") is None
            # Only one Redis attempt despite two calls
            assert mock_cache.get.call_count == 1

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_real_manifest_replaces_negative_cache(self):
        # Start with missing manifest
        assert resolve_version("1") is None

        # Now populate Redis with a real manifest
        manifest = _make_manifest(
            versions=["1.358.0"],
            pointers={"1": "1.358.0", "1.358": "1.358.0"},
        )
        cache.set(REDIS_POINTER_MAP_KEY, json.dumps(manifest))

        # Expire the negative cache
        sv._cached_manifest.cached_at = 0  # type: ignore

        # Should now resolve
        assert resolve_version("1") == "1.358.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_recovers_manifest_from_s3_on_redis_miss(self, mock_s3_read):
        manifest = _make_manifest(
            versions=["1.358.0"],
            pointers={"1": "1.358.0", "1.358": "1.358.0"},
        )
        mock_s3_read.return_value = json.dumps(manifest)

        # Redis is empty, but S3 has the manifest
        assert resolve_version("1") == "1.358.0"
        mock_s3_read.assert_called_once_with(sv.S3_MANIFEST_KEY, missing_ok=True)

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_s3_recovery_backfills_redis(self, mock_s3_read):
        manifest = _make_manifest(
            versions=["1.358.0"],
            pointers={"1": "1.358.0", "1.358": "1.358.0"},
        )
        mock_s3_read.return_value = json.dumps(manifest)

        assert resolve_version("1") == "1.358.0"

        # Redis should now have the manifest
        raw = cache.get(REDIS_POINTER_MAP_KEY)
        assert raw is not None
        assert json.loads(raw)["pointers"]["1"] == "1.358.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_s3_recovery_works_when_redis_completely_down(self, mock_s3_read):
        manifest = _make_manifest(
            versions=["1.358.0"],
            pointers={"1": "1.358.0", "1.358": "1.358.0"},
        )
        mock_s3_read.return_value = json.dumps(manifest)

        with patch("posthog.models.js_snippet_versioning.cache") as mock_cache:
            mock_cache.get.side_effect = ConnectionError("Redis unavailable")
            mock_cache.set.side_effect = ConnectionError("Redis unavailable")

            # S3 recovery succeeds and resolves correctly despite Redis being down
            assert resolve_version("1") == "1.358.0"

            # Second call uses in-process cache, no more S3 reads
            assert resolve_version("1") == "1.358.0"
            assert mock_s3_read.call_count == 1

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_s3_recovery_is_throttled(self, mock_s3_read):
        mock_s3_read.return_value = None  # S3 also empty

        assert resolve_version("1") is None
        assert resolve_version("1") is None
        # S3 only called once despite two resolve_version calls
        assert mock_s3_read.call_count == 1


class TestSyncTask(SimpleTestCase):
    def setUp(self):
        _reset_caches()

    def tearDown(self):
        cache.delete(REDIS_POINTER_MAP_KEY)
        _reset_caches()

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_write")
    @patch("posthog.models.js_snippet_versioning.validate_version_artifacts")
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_syncs_versions_json_to_redis(self, mock_read, mock_validate, _mock_write):
        entries = json.dumps(
            [
                {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
                {"version": "1.359.0", "timestamp": "2025-01-20T00:00:00Z"},
            ]
        )
        mock_read.return_value = entries
        mock_validate.return_value = True

        sync_js_snippet_manifest()

        raw = cache.get(REDIS_POINTER_MAP_KEY)
        manifest = json.loads(raw)
        assert manifest["versions"] == ["1.358.0", "1.359.0"]
        assert manifest["pointers"]["1"] == "1.359.0"
        assert manifest["pointers"]["1.358"] == "1.358.0"
        assert manifest["pointers"]["1.359"] == "1.359.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.validate_version_artifacts")
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_rejects_update_when_no_viable_version(self, mock_read, mock_validate):
        entries = [{"version": "99.99.99", "timestamp": "2025-01-20T00:00:00Z"}]
        mock_read.return_value = json.dumps(entries)
        mock_validate.return_value = False

        sync_js_snippet_manifest()

        assert cache.get(REDIS_POINTER_MAP_KEY) is None

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_write")
    @patch("posthog.models.js_snippet_versioning.validate_version_artifacts")
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_falls_back_to_next_version_when_latest_missing(self, mock_read, mock_validate, _mock_write):
        # 1.9.0 vs 1.10.0: string sort would rank "1.9.0" > "1.10.0",
        # but semver correctly ranks 1.10.0 > 1.9.0
        entries = json.dumps(
            [
                {"version": "1.9.0", "timestamp": "2025-01-15T00:00:00Z"},
                {"version": "1.10.0", "timestamp": "2025-01-20T00:00:00Z"},
            ]
        )
        mock_read.return_value = entries
        # 1.10.0 is missing artifacts, 1.9.0 is fine
        mock_validate.side_effect = lambda v: v != "1.10.0"

        sync_js_snippet_manifest()

        raw = cache.get(REDIS_POINTER_MAP_KEY)
        manifest = json.loads(raw)
        assert manifest["pointers"]["1"] == "1.9.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_raises_when_versions_json_is_empty(self, mock_read):
        from posthog.models.js_snippet_versioning import ManifestSyncError

        mock_read.return_value = json.dumps([])
        with self.assertRaises(ManifestSyncError):
            sync_manifest_from_s3()

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_raises_when_all_versions_yanked(self, mock_read):
        from posthog.models.js_snippet_versioning import ManifestSyncError

        entries = [{"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z", "yanked": True}]
        mock_read.return_value = json.dumps(entries)
        with self.assertRaises(ManifestSyncError):
            sync_manifest_from_s3()

    @override_settings(POSTHOG_JS_S3_BUCKET="")
    def test_noop_when_versioning_disabled(self):
        sync_js_snippet_manifest()
        assert cache.get(REDIS_POINTER_MAP_KEY) is None


class TestChangedPointers(SimpleTestCase):
    def test_detects_changed_value(self):
        assert changed_pointers({"1": "1.358.0"}, {"1": "1.359.0"}) == {"1"}

    def test_detects_added_pointer(self):
        assert changed_pointers({}, {"1": "1.359.0"}) == {"1"}

    def test_detects_removed_pointer(self):
        assert changed_pointers({"1": "1.359.0"}, {}) == {"1"}

    def test_no_changes(self):
        assert changed_pointers({"1": "1.359.0"}, {"1": "1.359.0"}) == set()


class TestSyncManifestPurge(SimpleTestCase):
    def setUp(self):
        _reset_caches()

    def tearDown(self):
        cache.delete(REDIS_POINTER_MAP_KEY)
        _reset_caches()

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_write")
    @patch("posthog.models.remote_config.RemoteConfig.purge_cdn_by_tag")
    @patch("posthog.models.js_snippet_versioning.validate_version_artifacts")
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_purges_changed_pointers(self, mock_read, mock_validate, mock_purge, _mock_write):
        # Seed old manifest
        old_manifest = _make_manifest(
            versions=["1.358.0"],
            pointers={"1": "1.358.0", "1.358": "1.358.0"},
        )
        cache.set(REDIS_POINTER_MAP_KEY, json.dumps(old_manifest))

        # New versions.json adds 1.359.0 which becomes the new "1" pointer
        mock_read.return_value = json.dumps(
            [
                {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
                {"version": "1.359.0", "timestamp": "2025-01-20T00:00:00Z"},
            ]
        )
        mock_validate.return_value = True

        sync_manifest_from_s3()

        purged_tags = {call.args[0] for call in mock_purge.call_args_list}
        assert "posthog-js-1" in purged_tags
        assert "posthog-js-1.359" in purged_tags
        assert "posthog-js-1.358" not in purged_tags

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_write")
    @patch("posthog.models.remote_config.RemoteConfig.purge_cdn_by_tag")
    @patch("posthog.models.js_snippet_versioning.validate_version_artifacts")
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_no_purge_when_pointers_unchanged(self, mock_read, mock_validate, mock_purge, _mock_write):
        # Seed old manifest with same data as new
        old_manifest = _make_manifest(
            versions=["1.358.0"],
            pointers={"1": "1.358.0", "1.358": "1.358.0"},
        )
        cache.set(REDIS_POINTER_MAP_KEY, json.dumps(old_manifest))

        mock_read.return_value = json.dumps(
            [
                {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
            ]
        )
        mock_validate.return_value = True

        sync_manifest_from_s3()

        mock_purge.assert_not_called()

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    @patch("posthog.models.js_snippet_versioning.s3_write")
    @patch("posthog.models.remote_config.RemoteConfig.purge_cdn_by_tag")
    @patch("posthog.models.js_snippet_versioning.validate_version_artifacts")
    @patch("posthog.models.js_snippet_versioning.s3_read")
    def test_purges_all_pointers_on_first_sync(self, mock_read, mock_validate, mock_purge, _mock_write):
        # No existing manifest in Redis
        mock_read.return_value = json.dumps(
            [
                {"version": "1.358.0", "timestamp": "2025-01-15T00:00:00Z"},
            ]
        )
        mock_validate.return_value = True

        sync_manifest_from_s3()

        purged_tags = {call.args[0] for call in mock_purge.call_args_list}
        assert "posthog-js-1" in purged_tags
        assert "posthog-js-1.358" in purged_tags
