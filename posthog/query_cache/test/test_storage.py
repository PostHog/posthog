import pickle
import hashlib
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import zstd
from parameterized import parameterized

from posthog.query_cache import (
    QueryCache,
    get_stale_insights,
    storage as qc_storage,
)
from posthog.query_cache.serialization import QUERY_CACHE_SPLIT_MAGIC, encode_split_cached_response
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
        self.fail_writes = False
        self.fail_reads = False

    def write(self, bucket: str, key: str, content: bytes, extras: dict | None = None) -> None:
        if self.fail_writes:
            raise ObjectStorageError("write failed")
        self.objects[(bucket, key)] = content

    def read_bytes(self, bucket: str, key: str, *, missing_ok: bool = False) -> bytes | None:
        if self.fail_reads:
            raise ObjectStorageError("read failed")
        if (bucket, key) not in self.objects:
            if missing_ok:
                return None
            raise ObjectStorageError("read failed")
        return self.objects[(bucket, key)]


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


def _redis_raw(cache_key: str) -> bytes | None:
    # Reach the client through the module so the fakeredis monkeypatch in conftest applies.
    return qc_storage.query_cache_raw_client().get(entry_redis_key(cache_key))


def _incompressible_rows(count: int) -> list[str]:
    return [hashlib.sha256(str(i).encode()).hexdigest() for i in range(count)]


class TestStoredValueFormats(BaseTest):
    def test_inline_values_are_stored_compressed_and_round_trip(self):
        cache_key = f"storage_inline_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)
        response = {"is_cached": False, "results": [{"data": _incompressible_rows(10)}], "cache_key": "k"}

        cache.store_result(response=response, target_age=None)

        raw = _redis_raw(cache_key)
        assert raw is not None
        assert raw.startswith(ZSTD_FRAME_MAGIC)
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


@override_settings(QUERY_CACHE_S3_MIN_COMPRESSED_BYTES=64)
class TestQueryCacheS3Routing(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.storage = FakeObjectStorage()
        storage_patcher = patch("posthog.query_cache.storage.object_storage_client", return_value=self.storage)
        storage_patcher.start()
        self.addCleanup(storage_patcher.stop)

    def _large_response(self) -> dict:
        return {"is_cached": False, "results": [{"data": _incompressible_rows(10)}], "cache_key": "k"}

    def _small_response(self) -> dict:
        return {"is_cached": False, "results": [], "cache_key": "k"}

    def _redis_holds_pointer(self, cache_key: str) -> bool:
        raw = _redis_raw(cache_key)
        assert raw is not None
        return raw.startswith(S3_POINTER_MAGIC)

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

    def test_small_result_stays_inline_when_flag_on(self):
        cache_key = f"s3_on_small_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)

        with patch("posthog.query_cache.storage.s3_write_mode", return_value="on"):
            cache.store_result(response=self._small_response(), target_age=None)

        assert self.storage.objects == {}
        assert not self._redis_holds_pointer(cache_key)
        assert cache.lookup().entry is not None

    @parameterized.expand(
        [
            # Both payloads serialize well past the threshold; only their compressed sizes differ.
            ("compressible_stays_inline", {"data": ["x" * 20000]}, False),
            ("incompressible_goes_to_s3", {"data": _incompressible_rows(50)}, True),
        ]
    )
    @override_settings(QUERY_CACHE_S3_MIN_COMPRESSED_BYTES=1000)
    def test_threshold_applies_to_compressed_size(self, _name, result, expect_pointer):
        cache_key = f"s3_threshold_{_name}_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)
        response = {"is_cached": False, "results": [result], "cache_key": "k"}

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

    def test_missing_blob_reads_as_miss_and_drops_pointer(self):
        cache_key = f"s3_missing_{self.team.pk}"
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key, insight_id=1)

        with patch("posthog.query_cache.storage.s3_write_mode", return_value="on"):
            cache.store_result(response=self._large_response(), target_age=None)
        self.storage.objects.clear()

        assert cache.lookup().entry is None
        assert _redis_raw(cache_key) is None

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
