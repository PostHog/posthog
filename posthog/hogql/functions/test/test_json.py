from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.functions.clickhouse.json import looks_like_clickhouse_type_name


class TestLooksLikeClickHouseTypeName(SimpleTestCase):
    @parameterized.expand(
        [
            ("String",),
            ("  String  ",),
            ("string",),
            ("Nullable(String)",),
            ("Array(Int64)",),
            ("LowCardinality(Nullable(String))",),
            ("Map(String, Array(Tuple(String, Float64)))",),
            ("Tuple(a String, b Nullable(Int64))",),
            ("DateTime64(6, 'UTC')",),
            ("Enum8('a(' = 1, 'b\\')' = 2)",),
            ("Decimal(10, 2)",),
            ("AggregateFunction(quantiles(0.5, 0.9), UInt64)",),
            ("JSON(max_dynamic_paths = 10, SKIP a.b)",),
            ("DOUBLE PRECISION",),
            ("double precision",),
            ("NATIONAL CHAR VARYING",),
            ("CHAR VARYING(255)",),
            ("BINARY LARGE OBJECT",),
            ("INT UNSIGNED",),
            ("INT(11) UNSIGNED",),
            ("`String`",),
            ("MadeUpButWellFormedType",),
        ]
    )
    def test_accepts_type_name_syntax(self, type_name: str) -> None:
        assert looks_like_clickhouse_type_name(type_name)

    @parameterized.expand(
        [
            ("",),
            ("   ",),
            ("content class years",),
            ("String Int64",),
            ("Array(Int64) extra",),
            ("(String)",),
            ("Array(Int64",),
            ("Array(Int64))",),
            ("Array)Int64(",),
            ("'String'",),
            ("Enum8('a = 1)",),
            ("1",),
            ("$browser",),
            ("properties.$browser",),
            ("String,",),
            ("Array(Int64), String",),
        ]
    )
    def test_rejects_text_that_is_not_a_type(self, type_name: str) -> None:
        assert not looks_like_clickhouse_type_name(type_name)
