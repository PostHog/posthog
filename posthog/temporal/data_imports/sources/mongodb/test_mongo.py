import uuid
import datetime

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from bson import Binary, DatetimeMS, ObjectId
from bson.binary import UUID_SUBTYPE
from parameterized import parameterized
from pymongo.server_description import ServerDescription

from posthog.temporal.data_imports.sources.mongodb.mongo import (
    _make_safe_server_selector,
    _process_doc_with_field_logging,
    _process_nested_value,
)


class TestSafeServerSelector(SimpleTestCase):
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_filters_out_servers_with_internal_ips(self):
        selector = _make_safe_server_selector(team_id=999)
        servers = [
            ServerDescription(("10.0.0.1", 27017)),
            ServerDescription(("8.8.8.8", 27017)),
        ]

        result = selector(servers)

        assert len(result) == 1
        assert result[0].address == ("8.8.8.8", 27017)

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_returns_empty_when_all_servers_internal(self):
        selector = _make_safe_server_selector(team_id=999)
        servers = [
            ServerDescription(("10.0.0.1", 27017)),
            ServerDescription(("192.168.1.1", 27017)),
        ]

        result = selector(servers)

        assert result == []

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_allows_all_public_servers(self):
        selector = _make_safe_server_selector(team_id=999)
        servers = [
            ServerDescription(("8.8.8.8", 27017)),
            ServerDescription(("1.1.1.1", 27017)),
        ]

        result = selector(servers)

        assert len(result) == 2

    @parameterized.expand(
        [
            ("loopback", "127.0.0.1"),
            ("link_local_imds", "169.254.169.254"),
            ("private_172", "172.16.0.1"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_blocks_various_internal_addresses(self, _name: str, host: str):
        selector = _make_safe_server_selector(team_id=999)
        servers = [ServerDescription((host, 27017))]

        result = selector(servers)

        assert result == []

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_whitelisted_team_allows_internal_ips(self):
        selector = _make_safe_server_selector(team_id=2)
        servers = [ServerDescription(("10.0.0.1", 27017))]

        result = selector(servers)

        assert len(result) == 1

    @patch("posthog.temporal.data_imports.sources.common.mixins.is_cloud", return_value=False)
    def test_self_hosted_allows_internal_ips(self, _mock_is_cloud):
        selector = _make_safe_server_selector(team_id=999)
        servers = [ServerDescription(("10.0.0.1", 27017))]

        result = selector(servers)

        assert len(result) == 1


class TestProcessNestedValue(SimpleTestCase):
    def test_objectid_is_stringified(self):
        oid = ObjectId()
        assert _process_nested_value(oid) == str(oid)

    def test_uuid_is_stringified(self):
        u = uuid.UUID("00000015-af12-f829-04fe-1f5e8f1a5230")
        assert _process_nested_value(u) == "00000015-af12-f829-04fe-1f5e8f1a5230"

    def test_binary_subtype_4_decodes_as_canonical_uuid(self):
        expected_uuid = uuid.UUID("00000015-af12-f829-04fe-1f5e8f1a5230")
        binary = Binary(expected_uuid.bytes, UUID_SUBTYPE)

        assert _process_nested_value(binary) == str(expected_uuid)

    def test_binary_legacy_subtype_3_decodes_as_uuid(self):
        expected_uuid = uuid.UUID("00000015-af12-f829-04fe-1f5e8f1a5230")
        binary = Binary(expected_uuid.bytes, 3)

        assert _process_nested_value(binary) == str(expected_uuid)

    def test_binary_non_uuid_subtype_falls_back_to_base64(self):
        import base64

        raw = b"\x00\x01\x02\x03payload"
        binary = Binary(raw, 0)

        assert _process_nested_value(binary) == base64.b64encode(raw).decode("ascii")

    def test_binary_uuid_subtype_with_wrong_length_falls_back_to_base64(self):
        import base64

        # Subtype 4 but not 16 bytes — can't be a UUID, must not crash.
        raw = b"\x00\x01\x02"
        binary = Binary(raw, UUID_SUBTYPE)

        assert _process_nested_value(binary) == base64.b64encode(raw).decode("ascii")

    def test_nested_dict_with_binary_uuid(self):
        expected_uuid = uuid.UUID("00000015-af12-f829-04fe-1f5e8f1a5230")
        value = {
            "user": {
                "_id": Binary(expected_uuid.bytes, UUID_SUBTYPE),
                "name": "Alice",
            },
        }

        result = _process_nested_value(value)

        assert result == {
            "user": {
                "_id": str(expected_uuid),
                "name": "Alice",
            }
        }

    def test_list_with_mixed_bson_types(self):
        oid = ObjectId()
        u = uuid.UUID("00000015-af12-f829-04fe-1f5e8f1a5230")
        value = [oid, Binary(u.bytes, UUID_SUBTYPE), "plain"]

        assert _process_nested_value(value) == [str(oid), str(u), "plain"]

    def test_plain_values_pass_through(self):
        assert _process_nested_value(42) == 42
        assert _process_nested_value("hello") == "hello"
        assert _process_nested_value(None) is None
        assert _process_nested_value(True) is True

    def test_never_produces_bytes_repr(self):
        # Regression: Binary/UUID must never leak as b'\x...' repr downstream.
        u = uuid.UUID("00000015-af12-f829-04fe-1f5e8f1a5230")
        binary = Binary(u.bytes, UUID_SUBTYPE)

        result = _process_nested_value(binary)

        assert isinstance(result, str)
        assert not result.startswith("b'")
        assert "\\x" not in result

    def test_datetime_in_range_passes_through(self):
        # Native datetime (in-range under DATETIME_AUTO) is returned unchanged.
        dt = datetime.datetime(2024, 6, 1, 12, 30, 0)
        assert _process_nested_value(dt) is dt

    def test_datetime_ms_in_range_converted_to_datetime(self):
        # DatetimeMS that lies within datetime range (pymongo could return this
        # under DATETIME_MS; under DATETIME_AUTO it's only returned for out-of-range,
        # but the helper must still handle the in-range case gracefully).
        ms = 1_700_000_000_000  # 2023-11-14T22:13:20Z
        result = _process_nested_value(DatetimeMS(ms))
        assert isinstance(result, datetime.datetime)

    def test_datetime_ms_year_zero_becomes_none(self):
        # Customer's "year 0 is out of range" BSON value.
        year_zero_ms = -62167219200000  # 0000-01-01T00:00:00Z
        assert _process_nested_value(DatetimeMS(year_zero_ms)) is None

    def test_datetime_ms_far_future_becomes_none(self):
        # 32-bit overflow / year > 9999 ms value.
        far_future_ms = 253_402_300_800_000 * 10
        assert _process_nested_value(DatetimeMS(far_future_ms)) is None

    def test_null_passes_through(self):
        # BSON null → Python None, must survive all transformations untouched.
        assert _process_nested_value(None) is None

    def test_nested_dict_with_out_of_range_datetime(self):
        value = {
            "user": {
                "dateOfBirth": DatetimeMS(-62167219200000),
                "createdAt": datetime.datetime(2024, 1, 1),
            },
        }

        result = _process_nested_value(value)

        assert result == {
            "user": {
                "dateOfBirth": None,
                "createdAt": datetime.datetime(2024, 1, 1),
            }
        }


class TestProcessDocWithFieldLogging(SimpleTestCase):
    def _logger(self) -> MagicMock:
        return MagicMock()

    def test_happy_path_passes_through_all_fields(self):
        logger = self._logger()
        doc = {"_id": "abc", "name": "Alice", "age": 42}

        result = _process_doc_with_field_logging(doc, "users", logger)

        assert result == {"_id": "abc", "name": "Alice", "age": 42}
        logger.exception.assert_not_called()

    def test_failed_field_reraises_and_logs_field_name(self):
        logger = self._logger()

        class BadDict(dict):
            def items(self):
                raise RuntimeError("synthetic items() failure")

        doc = {"_id": "abc", "good": "value", "bad_field": BadDict()}

        # Must re-raise so the sync fails fast rather than silently nulling data.
        with self.assertRaises(RuntimeError):
            _process_doc_with_field_logging(doc, "users", logger)

        logger.exception.assert_called_once()
        log_msg = logger.exception.call_args[0][0]
        assert "bad_field" in log_msg
        assert "users" in log_msg
        assert "_id=abc" in log_msg

    def test_failure_points_at_first_failing_field(self):
        logger = self._logger()

        class BadList(list):
            def __iter__(self):
                raise RuntimeError("synthetic iter failure")

        # `broken` comes before `last` — must raise at `broken` without processing `last`.
        doc = {
            "_id": "abc",
            "first": "ok",
            "broken": BadList(),
            "last": "also_ok",
        }

        with self.assertRaises(RuntimeError):
            _process_doc_with_field_logging(doc, "orders", logger)

        log_msg = logger.exception.call_args[0][0]
        assert "'broken'" in log_msg

    def test_log_includes_unavailable_id_when_id_lookup_fails(self):
        logger = self._logger()

        class DictNoId(dict):
            def get(self, key, default=None):
                if key == "_id":
                    raise RuntimeError("cannot access _id")
                return super().get(key, default)

        class BadList(list):
            def __iter__(self):
                raise RuntimeError("synthetic iter failure")

        doc = DictNoId({"broken": BadList()})

        with self.assertRaises(RuntimeError):
            _process_doc_with_field_logging(doc, "things", logger)

        log_msg = logger.exception.call_args[0][0]
        assert "_id=<unavailable>" in log_msg
