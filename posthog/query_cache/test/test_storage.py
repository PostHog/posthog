import pickle
import hashlib
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import zstd
from parameterized import parameterized

from posthog.query_cache import (
    QueryCache,
    get_stale_insights,
    storage as qc_storage,
)
from posthog.query_cache.serialization import QUERY_CACHE_SPLIT_MAGIC, encode_split_cached_response
from posthog.query_cache.size_tracker import TeamCacheSizeTracker
from posthog.query_cache.storage import (
    S3_POINTER_MAGIC,
    ZSTD_FRAME_MAGIC,
    S3BlobPointer,
    decode_pointer,
    encode_pointer,
    entry_redis_key,
    is_s3_pointer,
    s3_write_mode,
)
from posthog.storage.object_storage import ObjectStorageError


class FakeObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.written_keys: list[str] = []
        self.fail_writes = False
        self.fail_reads = False

    def write(self, bucket: str, key: str, content: bytes, extras: dict | None = None) -> None:
        if self.fail_writes:
            raise ObjectStorageError("write failed")
        self.objects[(bucket, key)] = content
        self.written_keys.append(key)

    def read_bytes(self, bucket: str, key: str, *, missing_ok: bool = False) -> bytes | None:
        if self.fail_reads:
            raise ObjectStorageError("read failed")
        if (bucket, key) not in self.objects:
            if missing_ok:
                return None
            raise ObjectStorageError("read failed")
        return self.objects[(bucket, key)]

    def delete(self, bucket: str, key: str) -> None:
        self.objects.pop((bucket, key), None)


class TestS3PointerCodec(SimpleTestCase):
    def test_pointer_round_trips(self):
        pointer = S3BlobPointer(bucket="cache-bucket", key="query_cache/1/some_key")
        assert decode_pointer(encode_pointer(pointer)) == pointer

    @parameterized.expand(
        [
            ("legacy_json_blob", b'{"results": []}'),
            ("split_format_blob", QUERY_CACHE_SPLIT_MAGIC + b"\x00rest"),
            ("empty", b""),
        ]
    )
    def test_blob_formats_are_not_pointers(self, _name, data):
        assert not is_s3_pointer(data)
        assert decode_pointer(data) is None

    @parameterized.expand(
        [
            ("not_json", S3_POINTER_MAGIC + b"notjson"),
            ("missing_keys", S3_POINTER_MAGIC + b'{"v": 1}'),
            ("unknown_version", S3_POINTER_MAGIC + b'{"v": 2, "b": "bucket", "k": "key"}'),
            ("non_string_key", S3_POINTER_MAGIC + b'{"v": 1, "b": "bucket", "k": [1, 2]}'),
        ]
    )
    def test_corrupt_pointer_decodes_to_none(self, _name, data):
        assert is_s3_pointer(data)
        assert decode_pointer(data) is None


@override_settings(OBJECT_STORAGE_ENABLED=True)
class TestS3WriteMode(SimpleTestCase):
    def test_disabled_object_storage_fails_closed(self):
        # UnavailableStorage swallows writes silently, so routing while storage is off would
        # store pointers to blobs that were never written.
        with (
            override_settings(OBJECT_STORAGE_ENABLED=False),
            patch("posthog.query_cache.storage._organization_id_for_team") as org_mock,
        ):
            assert s3_write_mode(team_id=1) == "off"
            org_mock.assert_not_called()

    @parameterized.expand(
        [
            ("on", "on"),
            ("shadow", "shadow"),
            (True, "off"),
            (False, "off"),
            (None, "off"),
            ("unknown-variant", "off"),
        ]
    )
    def test_only_known_variants_activate(self, variant, expected):
        with (
            patch("posthog.query_cache.storage._organization_id_for_team", return_value="0189-org-uuid"),
            patch("posthog.query_cache.storage.get_feature_flag_or_none", return_value=variant),
        ):
            assert s3_write_mode(team_id=1) == expected

    def test_unresolvable_organization_fails_closed_without_flag_evaluation(self):
        with (
            patch("posthog.query_cache.storage._organization_id_for_team", return_value=None),
            patch("posthog.query_cache.storage.get_feature_flag_or_none") as flag_mock,
        ):
            assert s3_write_mode(team_id=1) == "off"
            flag_mock.assert_not_called()

    def test_flag_evaluation_supplies_group_properties(self):
        # Without group_properties, an id-filtered rollout evaluates inconclusive under
        # only_evaluate_locally and silently reads as off.
        with (
            patch("posthog.query_cache.storage._organization_id_for_team", return_value="0189-org-uuid"),
            patch("posthog.query_cache.storage.get_feature_flag_or_none", return_value="on") as flag_mock,
        ):
            assert s3_write_mode(team_id=1) == "on"
        assert flag_mock.call_args.kwargs["groups"] == {"organization": "0189-org-uuid"}
        assert flag_mock.call_args.kwargs["group_properties"] == {"organization": {"id": "0189-org-uuid"}}


def _redis_raw(cache_key: str) -> bytes | None:
    # Reach the client through the module so the fakeredis monkeypatch in conftest applies.
    return qc_storage.query_cache_raw_client().get(entry_redis_key(cache_key))


def _incompressible_rows(count: int) -> list[str]:
    return [hashlib.sha256(str(i).encode()).hexdigest() for i in range(count)]


class TestStoredValueFormats(BaseTest):
    def test_inline_values_are_stored_compressed_and_round_trip(self):
        cache_key = f"storage_inline_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)
        response = {
            "is_cached": False,
            "results": [{"data": _incompressible_rows(10)}],
            "cache_key": "k",
            "last_refresh": "2026-08-01T00:00:00+00:00",
        }

        cache.store_result(response=response, target_age=None)

        raw = _redis_raw(cache_key)
        assert raw is not None
        assert raw.startswith(ZSTD_FRAME_MAGIC)
        entry = cache.lookup().entry
        assert entry is not None
        assert entry.as_full_response() == response
        freshness = cache.freshness()
        assert freshness is not None
        assert freshness.last_refresh == "2026-08-01T00:00:00+00:00"

    def test_compression_kill_switch_stores_raw_and_round_trips(self):
        cache_key = f"storage_kill_switch_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)
        response = {"is_cached": False, "results": [{"data": _incompressible_rows(10)}], "cache_key": "k"}

        with override_settings(USE_REDIS_COMPRESSION=False):
            cache.store_result(response=response, target_age=None)

        raw = _redis_raw(cache_key)
        assert raw is not None
        assert not raw.startswith(ZSTD_FRAME_MAGIC)
        entry = cache.lookup().entry
        assert entry is not None
        assert entry.as_full_response() == response

    def test_undecompressable_inline_value_reads_as_miss(self):
        cache_key = f"storage_bad_frame_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)
        response = {"is_cached": False, "results": [{"data": _incompressible_rows(10)}], "cache_key": "k"}
        cache.store_result(response=response, target_age=None)

        # A corrupt frame's declared content size raises MemoryError, not zstd.Error.
        with patch("posthog.query_cache.storage.zstd.decompress", side_effect=MemoryError):
            assert cache.lookup().entry is None
        # The miss must not mutate: the entry is still there and served once reads work again.
        entry = cache.lookup().entry
        assert entry is not None
        assert entry.as_full_response() == response

    @parameterized.expand(
        [
            ("pickled", False),
            ("zstd_compressed_pickled", True),
        ]
    )
    def test_legacy_django_redis_values_stay_readable(self, _name, compressed):
        cache_key = f"storage_legacy_{_name}_{self.team.pk}"
        response = {"is_cached": False, "results": [{"data": [1]}], "cache_key": "k"}
        legacy_value = pickle.dumps(encode_split_cached_response(response))
        if compressed:
            legacy_value = zstd.compress(legacy_value, 0, 1)
        qc_storage.query_cache_raw_client().set(entry_redis_key(cache_key), legacy_value)

        entry = QueryCache(team_id=self.team.pk, cache_key=cache_key).lookup().entry
        assert entry is not None
        assert entry.as_full_response() == response


@override_settings(QUERY_CACHE_S3_MIN_COMPRESSED_BYTES=64, OBJECT_STORAGE_ENABLED=True)
class TestQueryCacheS3Routing(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.storage = FakeObjectStorage()
        storage_patcher = patch("posthog.query_cache.storage.object_storage_client", return_value=self.storage)
        storage_patcher.start()
        self.addCleanup(storage_patcher.stop)
        # Run uploads inline so assertions right after store_result see the swapped pointer.
        self.upload_executor = MagicMock()
        self.upload_executor.submit.side_effect = lambda fn: fn()
        executor_patcher = patch("posthog.query_cache.storage._get_upload_executor", return_value=self.upload_executor)
        executor_patcher.start()
        self.addCleanup(executor_patcher.stop)

    def _large_response(self) -> dict:
        return {"is_cached": False, "results": [{"data": _incompressible_rows(10)}], "cache_key": "k"}

    def _small_response(self) -> dict:
        return {"is_cached": False, "results": [], "cache_key": "k"}

    def _redis_holds_pointer(self, cache_key: str) -> bool:
        raw = _redis_raw(cache_key)
        assert raw is not None
        return raw.startswith(S3_POINTER_MAGIC)

    def test_stale_upload_cannot_replace_a_newer_entry(self):
        cache_key = f"s3_race_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)
        pending: list = []
        self.upload_executor.submit.side_effect = pending.append

        older = {**self._large_response(), "cache_key": "older"}
        newer = {**self._large_response(), "cache_key": "newer"}
        with patch("posthog.query_cache.storage.s3_write_mode", return_value="on"):
            cache.store_result(response=older, target_age=None)
            cache.store_result(response=newer, target_age=None)
            older_upload, newer_upload = pending

            newer_upload()
            assert self._redis_holds_pointer(cache_key)
            older_upload()

        # The superseded upload deletes its own blob; only the winning upload's object remains.
        assert len(self.storage.objects) == 1
        entry = cache.lookup().entry
        assert entry is not None
        assert entry.as_full_response() == newer

        # A lost reply makes the redis client retry the swap script after it already landed.
        # The retry must report swapped even though `expected` no longer matches, because a
        # False return sends the upload down the superseded path, which deletes the blob the
        # live entry now points at.
        raw_pointer = _redis_raw(cache_key)
        assert raw_pointer is not None
        tracker = TeamCacheSizeTracker(team_id=self.team.pk)
        assert tracker.replace_value(cache_key, raw_pointer, ttl=600, expected=b"stale-inline-bytes") is True
        assert _redis_raw(cache_key) == raw_pointer

    def test_on_mode_large_result_round_trips_via_pointer(self):
        cache_key = f"s3_on_large_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)
        response = self._large_response()

        with patch("posthog.query_cache.storage.s3_write_mode", return_value="on"):
            cache.store_result(response=response, target_age=None)

        assert self._redis_holds_pointer(cache_key)
        assert len(self.storage.objects) == 1
        entry = cache.lookup().entry
        assert entry is not None
        assert entry.as_full_response() == response

    def test_replacing_a_pointer_entry_deletes_the_replaced_blob(self):
        cache_key = f"s3_fresh_object_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)
        first = self._large_response()
        second = {**self._large_response(), "cache_key": "second"}

        with patch("posthog.query_cache.storage.s3_write_mode", return_value="on"):
            cache.store_result(response=first, target_age=None)
            cache.store_result(response=second, target_age=None)

        # A shared object key would let overlapping recomputes overwrite each other's blob.
        assert len(set(self.storage.written_keys)) == 2
        # The second store replaced the first store's pointer, which enqueued a delete for its
        # blob (Celery runs eagerly under TEST); only the second store's object remains.
        assert len(self.storage.objects) == 1
        entry = cache.lookup().entry
        assert entry is not None
        assert entry.as_full_response() == second

    def test_inline_value_is_readable_during_the_upload(self):
        cache_key = f"s3_during_upload_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)
        observed: dict[str, bytes | None] = {}
        original_write = self.storage.write

        def write_and_peek(bucket: str, key: str, content: bytes, extras: dict | None = None) -> None:
            observed["during_upload"] = _redis_raw(cache_key)
            original_write(bucket, key, content, extras)

        with (
            patch.object(self.storage, "write", side_effect=write_and_peek),
            patch("posthog.query_cache.storage.s3_write_mode", return_value="on"),
        ):
            cache.store_result(response=self._large_response(), target_age=None)

        # Uploading before the inline write would reopen the window where concurrent
        # requests miss and recompute a result that just finished computing.
        assert observed["during_upload"] is not None
        assert observed["during_upload"].startswith(ZSTD_FRAME_MAGIC)
        assert self._redis_holds_pointer(cache_key)

    def test_freshness_probe_reads_pointer_without_s3(self):
        cache_key = f"s3_probe_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)
        assert cache.freshness() is None
        response = {**self._large_response(), "last_refresh": "2026-08-01T00:00:00+00:00"}

        with patch("posthog.query_cache.storage.s3_write_mode", return_value="on"):
            cache.store_result(response=response, target_age=None)

        assert self._redis_holds_pointer(cache_key)
        self.storage.fail_reads = True
        freshness = cache.freshness()
        assert freshness is not None
        assert freshness.last_refresh == "2026-08-01T00:00:00+00:00"

    @parameterized.expand(
        [
            # Below the compression floor: stored raw, never a candidate for S3.
            ("small_below_floor", [], False),
            # The next two serialize well past the threshold; only their compressed sizes differ.
            ("compressible_stays_inline", [{"data": ["x" * 20000]}], False),
            ("incompressible_goes_to_s3", [{"data": _incompressible_rows(50)}], True),
        ]
    )
    @override_settings(QUERY_CACHE_S3_MIN_COMPRESSED_BYTES=1000)
    def test_only_large_compressed_results_route_to_s3(self, _name, results, expect_pointer):
        cache_key = f"s3_threshold_{_name}_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)
        response = {"is_cached": False, "results": results, "cache_key": "k"}

        with patch("posthog.query_cache.storage.s3_write_mode", return_value="on"):
            cache.store_result(response=response, target_age=None)

        assert self._redis_holds_pointer(cache_key) == expect_pointer
        assert bool(self.storage.objects) == expect_pointer
        entry = cache.lookup().entry
        assert entry is not None
        assert entry.as_full_response() == response

    def test_shadow_mode_uploads_but_redis_stays_authoritative(self):
        cache_key = f"s3_shadow_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)
        response = self._large_response()

        with patch("posthog.query_cache.storage.s3_write_mode", return_value="shadow"):
            cache.store_result(response=response, target_age=None)

        assert len(self.storage.objects) == 1
        assert not self._redis_holds_pointer(cache_key)

        self.storage.objects.clear()
        entry = cache.lookup().entry
        assert entry is not None
        assert entry.as_full_response() == response

    def test_off_mode_never_touches_s3(self):
        cache_key = f"s3_off_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)

        with patch("posthog.query_cache.storage.s3_write_mode", return_value="off"):
            cache.store_result(response=self._large_response(), target_age=None)

        assert self.storage.objects == {}
        assert cache.lookup().entry is not None

    def test_s3_write_failure_falls_back_to_inline_blob(self):
        cache_key = f"s3_write_fail_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)
        response = self._large_response()
        self.storage.fail_writes = True

        with patch("posthog.query_cache.storage.s3_write_mode", return_value="on"):
            cache.store_result(response=response, target_age=None)

        assert not self._redis_holds_pointer(cache_key)
        entry = cache.lookup().entry
        assert entry is not None
        assert entry.as_full_response() == response

    def test_missing_blob_reads_as_miss_and_keeps_the_entry(self):
        cache_key = f"s3_missing_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)

        with patch("posthog.query_cache.storage.s3_write_mode", return_value="on"):
            cache.store_result(response=self._large_response(), target_age=None)
        self.storage.objects.clear()

        # Reads never mutate; the recompute a miss triggers is what overwrites dead entries.
        assert cache.lookup().entry is None
        assert self._redis_holds_pointer(cache_key)

    def test_transient_s3_error_keeps_pointer_and_recovers(self):
        cache_key = f"s3_transient_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)
        response = self._large_response()

        with patch("posthog.query_cache.storage.s3_write_mode", return_value="on"):
            cache.store_result(response=response, target_age=None)

        self.storage.fail_reads = True
        assert cache.lookup().entry is None
        assert self._redis_holds_pointer(cache_key)

        self.storage.fail_reads = False
        entry = cache.lookup().entry
        assert entry is not None
        assert entry.as_full_response() == response

    def test_pointer_write_updates_freshness_index(self):
        cache_key = f"s3_freshness_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=42)

        with patch("posthog.query_cache.storage.s3_write_mode", return_value="on"):
            cache.store_result(response=self._large_response(), target_age=datetime.now(UTC) - timedelta(minutes=5))

        assert "42:" in get_stale_insights(team_id=self.team.pk)
