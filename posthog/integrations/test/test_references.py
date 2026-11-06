from typing import Any
from uuid import UUID

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.integrations import IntegrationReference

UUID_TEXT = "0b7e8c3a-5f4d-4e2a-9c1b-2d3e4f5a6b7c"


class TestIntegrationReference(SimpleTestCase):
    @parameterized.expand(
        [
            ("zero", "0", IntegrationReference(legacy_id=0)),
            ("small", "7", IntegrationReference(legacy_id=7)),
            ("int32_max", "2147483647", IntegrationReference(legacy_id=2147483647)),
            ("beyond_int64", "18446744073709551616", IntegrationReference(legacy_id=2**64)),
            ("uuid", UUID_TEXT, IntegrationReference(uuid=UUID(UUID_TEXT))),
        ]
    )
    def test_parse_reads_the_canonical_forms_and_str_writes_them_back(
        self, _name: str, value: str, expected: IntegrationReference
    ) -> None:
        reference = IntegrationReference.parse(value)

        assert reference == expected
        assert str(reference) == value

    @parameterized.expand(
        [
            ("empty", ""),
            ("space", " "),
            ("leading_space", " 7"),
            ("trailing_newline", "7\n"),
            ("plus_sign", "+7"),
            ("minus_sign", "-7"),
            ("leading_zero", "07"),
            ("double_zero", "00"),
            ("decimal_point", "7.0"),
            ("underscore", "1_000"),
            ("exponent", "1e3"),
            ("non_ascii_digits", "١٢"),
            ("superscript_digit", "²"),
            ("uuid_upper_case", UUID_TEXT.upper()),
            ("uuid_without_hyphens", UUID_TEXT.replace("-", "")),
            ("uuid_with_braces", "{" + UUID_TEXT + "}"),
            ("uuid_urn", "urn:uuid:" + UUID_TEXT),
            ("uuid_with_space", UUID_TEXT + " "),
            ("garbage", "not-a-reference"),
            ("hex_int", "0x1f"),
        ]
    )
    def test_parse_rejects_every_other_string(self, _name: str, value: str) -> None:
        with self.assertRaises(ValueError):
            IntegrationReference.parse(value)

    @parameterized.expand([("int", 7), ("none", None), ("bytes", b"7")])
    def test_parse_rejects_a_value_that_is_not_a_string(self, _name: str, value: Any) -> None:
        with self.assertRaises(ValueError):
            IntegrationReference.parse(value)

    @parameterized.expand(
        [
            ("neither", {}),
            ("both", {"legacy_id": 7, "uuid": UUID(UUID_TEXT)}),
            ("negative_id", {"legacy_id": -1}),
            ("bool_id", {"legacy_id": True}),
            ("string_id", {"legacy_id": "7"}),
            ("string_uuid", {"uuid": UUID_TEXT}),
        ]
    )
    def test_constructor_rejects_an_invalid_reference(self, _name: str, kwargs: dict[str, Any]) -> None:
        with self.assertRaises(ValueError):
            IntegrationReference(**kwargs)

    @parameterized.expand([("zero", 0), ("int", 12), ("large", 2**40)])
    def test_from_legacy_id_round_trips(self, _name: str, legacy_id: int) -> None:
        reference = IntegrationReference.from_legacy_id(legacy_id)

        assert (reference.legacy_id, reference.uuid) == (legacy_id, None)
        assert IntegrationReference.parse(str(reference)) == reference
