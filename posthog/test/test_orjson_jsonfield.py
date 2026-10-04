import json
from typing import Any, cast

from django.db.models import JSONField
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.helpers.orjson_jsonfield import _orjson_from_db_value

# from_db_value ignores expression/connection in our patch; typed None keeps mypy happy.
_NULL = cast(Any, None)


class TestOrjsonJSONFieldDecode(SimpleTestCase):
    @parameterized.expand(
        [
            ("dict", {"key": "value", "count": 1}),
            ("nested", {"a": [1, 2, {"b": True}], "c": None}),
            ("list", [{"key": "x"}, {"key": "y"}]),
            ("unicode", {"name": "café ☕ 日本語"}),
            ("int64", {"id": 9007199254740993}),
            ("float", {"ratio": 1.5}),
            ("empty", {}),
            ("entitlements", [{"key": "sso", "name": "SSO", "limit": None}, {"key": "rbac"}]),
        ]
    )
    def test_decodes_identically_to_stdlib(self, _name: str, payload: Any) -> None:
        decoded = JSONField().from_db_value(json.dumps(payload), _NULL, _NULL)
        self.assertEqual(decoded, payload)
        self.assertEqual(decoded, json.loads(json.dumps(payload)))

    def test_patch_is_installed(self) -> None:
        # The other cases pass under unpatched Django too; this is what proves apply() ran.
        self.assertIs(JSONField.from_db_value, _orjson_from_db_value)

    def test_decodes_bytes_input(self) -> None:
        # psycopg can hand back bytes; Django types value as str|None, so cast for the type checker.
        self.assertEqual(JSONField().from_db_value(cast(Any, b'{"a": 1}'), _NULL, _NULL), {"a": 1})
        self.assertEqual(JSONField().from_db_value(cast(Any, bytearray(b'{"a": 1}')), _NULL, _NULL), {"a": 1})

    def test_none_passes_through(self) -> None:
        self.assertIsNone(JSONField().from_db_value(None, _NULL, _NULL))

    @parameterized.expand([("dict", {"a": 1}), ("list", [1, 2]), ("int", 5), ("bool", True)])
    def test_already_decoded_value_passes_through(self, _name: str, value: Any) -> None:
        # Django #36371: a backend/driver that returns a native type must not be re-parsed.
        self.assertEqual(JSONField().from_db_value(value, _NULL, _NULL), value)

    def test_invalid_json_returns_raw(self) -> None:
        self.assertEqual(JSONField().from_db_value("not json", _NULL, _NULL), "not json")

    def test_integers_within_64bit_stay_exact(self) -> None:
        for n in (9223372036854775807, 18446744073709551615):  # i64 max, u64 max
            self.assertEqual(JSONField().from_db_value(json.dumps({"n": n}), _NULL, _NULL), {"n": n})

    def test_integer_beyond_64bit_is_lossy_float(self) -> None:
        # Documents orjson's known limit (see module docstring): integers >= 2**64 decode to a
        # lossy float, not an exact int. Gated by JSONFIELD_ORJSON_DECODE; not present in jsonb config data.
        decoded = JSONField().from_db_value(json.dumps({"n": 2**64}), _NULL, _NULL)
        self.assertIsInstance(decoded["n"], float)

    def test_custom_decoder_still_uses_stdlib(self) -> None:
        # orjson can't accept a json.JSONDecoder, so a field with decoder= must fall back to stdlib.
        class TaggingDecoder(json.JSONDecoder):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(object_hook=self._hook, **kwargs)

            @staticmethod
            def _hook(obj: dict) -> dict:
                obj["_decoded_by"] = "custom"
                return obj

        decoded = JSONField(decoder=TaggingDecoder).from_db_value('{"a": 1}', _NULL, _NULL)
        self.assertEqual(decoded, {"a": 1, "_decoded_by": "custom"})
