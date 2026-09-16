from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.query_cache.serialization import QUERY_CACHE_SPLIT_MAGIC
from posthog.query_cache.storage import (
    S3_POINTER_MAGIC,
    S3BlobPointer,
    decode_pointer,
    encode_pointer,
    is_s3_pointer,
    s3_write_mode,
)


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
