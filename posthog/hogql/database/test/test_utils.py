from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.database.utils import get_join_field_chain, qualify_join_key_expr


class TestJoinKeyExtraction(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain_field", "distinct_id", ["distinct_id"]),
            ("wrapper_call", "upper(distinct_id)", ["distinct_id"]),
            ("nested_call", "toString(ifNull(distinct_id, ''))", ["distinct_id"]),
            # The field lives in a branch, not args[0] (which is the condition).
            (
                "conditional",
                "if(event = 'SaveProduct', properties.merchant_domain, NULL)",
                ["properties", "merchant_domain"],
            ),
        ]
    )
    def test_extracts_field_chain(self, _name: str, key: str, expected: list[str]) -> None:
        self.assertEqual(get_join_field_chain(key), expected)

    @parameterized.expand(
        [
            ("literal", "'SaveProduct'"),
            ("no_field_call", "now()"),
        ]
    )
    def test_returns_none_without_a_field(self, _name: str, key: str) -> None:
        # A fieldless key is an unsupported user configuration, not an internal error:
        # it must return None quietly rather than capturing an exception.
        self.assertIsNone(get_join_field_chain(key))

    @parameterized.expand(
        [
            ("plain_field", "distinct_id", "t.distinct_id"),
            ("wrapper_call", "upper(distinct_id)", "upper(t.distinct_id)"),
            # Every field reference must be qualified, including the one in the condition.
            (
                "conditional_qualifies_all_fields",
                "if(event = 'SaveProduct', properties.merchant_domain, NULL)",
                "if(equals(t.event, 'SaveProduct'), t.properties.merchant_domain, NULL)",
            ),
        ]
    )
    def test_qualifies_every_field_with_table_name(self, _name: str, key: str, expected: str) -> None:
        expr = qualify_join_key_expr(key, "t")
        assert expr is not None
        self.assertEqual(expr.to_hogql(), expected)

    def test_qualify_returns_none_without_a_field(self) -> None:
        self.assertIsNone(qualify_join_key_expr("'SaveProduct'", "t"))
