import json
from typing import Any

from django.db.models import JSONField
from django.test import SimpleTestCase

from parameterized import parameterized


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
        decoded = JSONField().from_db_value(json.dumps(payload), None, None)
        self.assertEqual(decoded, payload)
        self.assertEqual(decoded, json.loads(json.dumps(payload)))

    def test_none_passes_through(self) -> None:
        self.assertIsNone(JSONField().from_db_value(None, None, None))

    @parameterized.expand([("dict", {"a": 1}), ("list", [1, 2]), ("int", 5), ("bool", True)])
    def test_already_decoded_value_passes_through(self, _name: str, value: Any) -> None:
        # Django #36371: a backend/driver that returns a native type must not be re-parsed.
        # Also asserts the patch is live — unpatched Django would TypeError on json.loads(dict).
        self.assertEqual(JSONField().from_db_value(value, None, None), value)

    def test_invalid_json_returns_raw(self) -> None:
        self.assertEqual(JSONField().from_db_value("not json", None, None), "not json")

    def test_custom_decoder_still_uses_stdlib(self) -> None:
        # orjson can't accept a json.JSONDecoder, so a field with decoder= must fall back to stdlib.
        class TaggingDecoder(json.JSONDecoder):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(object_hook=self._hook, **kwargs)

            @staticmethod
            def _hook(obj: dict) -> dict:
                obj["_decoded_by"] = "custom"
                return obj

        decoded = JSONField(decoder=TaggingDecoder).from_db_value('{"a": 1}', None, None)
        self.assertEqual(decoded, {"a": 1, "_decoded_by": "custom"})
