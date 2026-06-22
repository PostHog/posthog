from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.hogql.query import snowflake_field_type_to_clickhouse_type

# Snowflake connector type codes (indices into FIELD_ID_TO_NAME). cursor.description
# reports the integer code, not a name — see snowflake_field_type_to_clickhouse_type.
FIXED = 0
REAL = 1
TEXT = 2
DATE = 3
TIMESTAMP_NTZ = 8
BOOLEAN = 13


class TestDirectSnowflakeQuery(APIBaseTest):
    @parameterized.expand(
        [
            # FIXED covers NUMBER/DECIMAL/INT; scale decides int vs decimal.
            ("number_decimal", FIXED, 2, "Decimal"),
            ("number_integer_scale_0", FIXED, 0, "Int64"),
            ("number_integer_scale_none", FIXED, None, "Int64"),
            ("real_float", REAL, None, "Float64"),
            ("text_varchar", TEXT, None, "String"),
            ("date", DATE, None, "Date"),
            ("timestamp_ntz", TIMESTAMP_NTZ, None, "DateTime64(6, 'UTC')"),
            ("boolean", BOOLEAN, None, "Bool"),
            ("unknown_code", 99999, None, "String"),
            ("non_integer_code", "NUMBER", None, "String"),
            ("none_code", None, None, "String"),
        ]
    )
    def test_snowflake_field_type_to_clickhouse_type(
        self, _name: str, type_code: object | None, scale: object | None, expected: str
    ):
        self.assertEqual(snowflake_field_type_to_clickhouse_type(type_code, scale), expected)
