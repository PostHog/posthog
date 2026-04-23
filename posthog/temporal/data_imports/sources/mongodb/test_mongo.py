import uuid
import base64
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
    CANONICAL_UUID_STR = "00000015-af12-f829-04fe-1f5e8f1a5230"
    CANONICAL_UUID = uuid.UUID(CANONICAL_UUID_STR)
    YEAR_ZERO_MS = -62167219200000  # 0000-01-01T00:00:00Z
    FAR_FUTURE_MS = 253_402_300_800_000 * 10  # year > 9999

    def test_objectid_is_stringified(self):
        oid = ObjectId()
        assert _process_nested_value(oid) == str(oid)

    def test_uuid_is_stringified(self):
        assert _process_nested_value(self.CANONICAL_UUID) == self.CANONICAL_UUID_STR

    def test_binary_legacy_subtype_3_decodes_as_uuid(self):
        # Subtype 4 (standard UUID) is pre-decoded to uuid.UUID by PyMongo's
        # codec and never reaches _convert_binary; only legacy subtype 3 exercises
        # the Binary → UUID branch here.
        binary = Binary(self.CANONICAL_UUID.bytes, 3)
        assert _process_nested_value(binary) == self.CANONICAL_UUID_STR

    @parameterized.expand(
        [
            ("generic_subtype", b"\x00\x01\x02\x03payload", 0),
            # Subtype 4 Binary should not reach _convert_binary in production
            # (codec decodes to uuid.UUID first), but if it does, the wrong-length
            # guard falls back to base64 rather than crashing.
            ("subtype_4_wrong_length", b"\x00\x01\x02", UUID_SUBTYPE),
            ("subtype_4_full_length", b"\x00" * 16, UUID_SUBTYPE),
        ]
    )
    def test_non_decodable_binary_falls_back_to_base64(self, _name: str, raw: bytes, subtype: int):
        binary = Binary(raw, subtype)
        assert _process_nested_value(binary) == base64.b64encode(raw).decode("ascii")

    def test_nested_dict_with_uuid(self):
        value = {
            "user": {
                "_id": self.CANONICAL_UUID,
                "name": "Alice",
            },
        }

        result = _process_nested_value(value)

        assert result == {
            "user": {
                "_id": self.CANONICAL_UUID_STR,
                "name": "Alice",
            }
        }

    def test_list_with_mixed_bson_types(self):
        oid = ObjectId()
        value = [oid, self.CANONICAL_UUID, "plain"]

        assert _process_nested_value(value) == [str(oid), self.CANONICAL_UUID_STR, "plain"]

    @parameterized.expand(
        [
            ("int", 42),
            ("string", "hello"),
            ("none", None),
            ("bool_true", True),
            ("bool_false", False),
            ("float", 3.14),
        ]
    )
    def test_plain_values_pass_through(self, _name: str, value):
        assert _process_nested_value(value) == value

    def test_never_produces_bytes_repr(self):
        # Regression: UUID must never leak as b'\x...' repr downstream.
        result = _process_nested_value(self.CANONICAL_UUID)

        assert isinstance(result, str)
        assert not result.startswith("b'")
        assert "\\x" not in result

    def test_datetime_in_range_passes_through(self):
        # Native datetime (in-range under DATETIME_AUTO) is returned unchanged.
        dt = datetime.datetime(2024, 6, 1, 12, 30, 0)
        assert _process_nested_value(dt) is dt

    def test_datetime_ms_in_range_converted_to_datetime(self):
        # DatetimeMS within the datetime representable range: as_datetime succeeds.
        # Under DATETIME_AUTO this only arises for out-of-range values, but the
        # helper must still handle in-range DatetimeMS gracefully if it appears.
        ms = 1_700_000_000_000  # 2023-11-14T22:13:20Z
        result = _process_nested_value(DatetimeMS(ms))
        assert isinstance(result, datetime.datetime)

    @parameterized.expand(
        [
            ("year_zero", YEAR_ZERO_MS),
            ("far_future", FAR_FUTURE_MS),
        ]
    )
    def test_datetime_ms_out_of_range_becomes_none(self, _name: str, ms: int):
        assert _process_nested_value(DatetimeMS(ms)) is None

    def test_nested_dict_with_out_of_range_datetime(self):
        value = {
            "user": {
                "dateOfBirth": DatetimeMS(self.YEAR_ZERO_MS),
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
