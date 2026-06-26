from datetime import datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.errors import QueryError, ResolutionError
from posthog.hogql.escape_sql import (
    escape_clickhouse_identifier,
    escape_clickhouse_string,
    escape_hogql_identifier,
    escape_hogql_string,
    escape_postgres_identifier,
)
from posthog.hogql.parser import parse_expr

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.utils import UUIDT

_ROUNDTRIP_IDENTIFIER_SAMPLES = [
    "back`tick",
    "a``b",
    "`leading",
    "trailing`",
    "``",
    "a\\b",
    "a\\`b",
    "`a\\`b`",
    "with space",
    "a.b.c",
]


class TestPrintString(BaseTest):
    def test_sanitize_hogql_identifier(self):
        self.assertEqual(escape_hogql_identifier("a"), "a")
        self.assertEqual(escape_hogql_identifier("$browser"), "$browser")
        self.assertEqual(escape_hogql_identifier("0asd"), "`0asd`")
        self.assertEqual(escape_hogql_identifier("123"), "`123`")
        self.assertEqual(escape_hogql_identifier("event"), "event")
        self.assertEqual(escape_hogql_identifier("a b c"), "`a b c`")
        self.assertEqual(escape_hogql_identifier("a.b.c"), "`a.b.c`")
        self.assertEqual(escape_hogql_identifier("a-b-c"), "`a-b-c`")
        self.assertEqual(escape_hogql_identifier("a#$#"), "`a#$#`")
        self.assertEqual(escape_hogql_identifier("back`tick"), "`back``tick`")
        self.assertEqual(escape_hogql_identifier("single'quote"), "`single'quote`")
        self.assertEqual(escape_hogql_identifier('double"quote'), '`double"quote`')
        self.assertEqual(
            escape_hogql_identifier("other escapes: \b \f \n \t \0 \a \v \\"),
            "`other escapes: \\b \\f \\n \\t \\0 \\a \\v \\\\`",
        )

    def test_sanitize_clickhouse_identifier(self):
        self.assertEqual(escape_clickhouse_identifier("a"), "a")
        self.assertEqual(escape_clickhouse_identifier("$browser"), "`$browser`")
        self.assertEqual(escape_clickhouse_identifier("0asd"), "`0asd`")
        self.assertEqual(escape_clickhouse_identifier("123"), "`123`")
        self.assertEqual(escape_clickhouse_identifier("event"), "event")
        self.assertEqual(escape_clickhouse_identifier("a b c"), "`a b c`")
        self.assertEqual(escape_clickhouse_identifier("a.b.c"), "`a.b.c`")
        self.assertEqual(escape_clickhouse_identifier("a-b-c"), "`a-b-c`")
        self.assertEqual(escape_clickhouse_identifier("a#$#"), "`a#$#`")
        self.assertEqual(escape_clickhouse_identifier("back`tick"), "`back``tick`")
        self.assertEqual(escape_clickhouse_identifier("single'quote"), "`single'quote`")
        self.assertEqual(escape_clickhouse_identifier('double"quote'), '`double"quote`')
        self.assertEqual(
            escape_clickhouse_identifier("other escapes: \b \f \n \t \0 \a \v \\"),
            "`other escapes: \\b \\f \\n \\t \\0 \\a \\v \\\\`",
        )

    @parameterized.expand(
        [
            (f"{label}-{backend}-{i}", escape_fn, backend, sample)
            for label, escape_fn in [("hogql", escape_hogql_identifier), ("clickhouse", escape_clickhouse_identifier)]
            for backend in ["rust-py", "cpp-json"]
            for i, sample in enumerate(_ROUNDTRIP_IDENTIFIER_SAMPLES)
        ]
    )
    def test_identifier_roundtrips_through_production_parser(self, _name, escape_fn, backend, identifier):
        # Round-trips through the real parsers, not the lenient parse_string_literal_text; the clickhouse case still parses via the HogQL parser (shared grammar), not ClickHouse itself.
        escaped = escape_fn(identifier)
        node = parse_expr(escaped, backend=backend)
        assert isinstance(node, ast.Field), f"{identifier!r} escaped to {escaped!r} did not parse to a Field"
        self.assertEqual(node.chain, [identifier], f"{identifier!r} escaped to {escaped!r} did not round-trip")

    def test_sanitize_postgres_identifier(self):
        self.assertEqual(escape_postgres_identifier("a"), "a")
        self.assertEqual(escape_postgres_identifier("$browser"), '"$browser"')
        self.assertEqual(escape_postgres_identifier("0asd"), '"0asd"')
        self.assertEqual(escape_postgres_identifier("123"), '"123"')
        self.assertEqual(escape_postgres_identifier("event"), "event")
        self.assertEqual(escape_postgres_identifier("a b c"), '"a b c"')
        self.assertEqual(escape_postgres_identifier("a.b.c"), '"a.b.c"')
        self.assertEqual(escape_postgres_identifier("a-b-c"), '"a-b-c"')
        self.assertEqual(escape_postgres_identifier("a#$#"), '"a#$#"')
        self.assertEqual(escape_postgres_identifier("back`tick"), '"back`tick"')
        self.assertEqual(escape_postgres_identifier("single'quote"), '"single\'quote"')
        self.assertEqual(escape_postgres_identifier('double"quote'), '"double""quote"')
        self.assertEqual(
            escape_postgres_identifier("other escapes: \b \f \n \t \0 \a \v \\"),
            '"other escapes: \b \f \n \t \0 \a \v \\"',
        )

    def test_escape_postgres_identifier_length(self):
        identifier_at_max_length = "a" * 63
        self.assertEqual(escape_postgres_identifier(identifier_at_max_length), identifier_at_max_length)

        identifier_exceeding_max_length = "a" * 64
        with self.assertRaises(QueryError) as context:
            escape_postgres_identifier(identifier_exceeding_max_length)
        self.assertIn("is too long. Maximum length is 63 characters", str(context.exception))

    def test_sanitize_clickhouse_string(self):
        self.assertEqual(escape_clickhouse_string("a"), "'a'")
        self.assertEqual(escape_clickhouse_string("$browser"), "'$browser'")
        self.assertEqual(escape_clickhouse_string("a b c"), "'a b c'")
        self.assertEqual(escape_clickhouse_string("a#$%#"), "'a#$%#'")
        self.assertEqual(escape_clickhouse_string("back`tick"), "'back`tick'")
        self.assertEqual(escape_clickhouse_string("single'quote"), "'single\\'quote'")
        self.assertEqual(escape_clickhouse_string('double"quote'), "'double\"quote'")
        self.assertEqual(
            escape_clickhouse_string("other escapes: \b \f \n \t \0 \a \v \\"),
            "'other escapes: \\b \\f \\n \\t \\0 \\a \\v \\\\'",
        )
        self.assertEqual(escape_clickhouse_string(["list", "things", []]), "['list', 'things', []]")
        self.assertEqual(escape_clickhouse_string(("tuple", "things", ())), "('tuple', 'things', ())")
        uuid = UUIDT()
        self.assertEqual(escape_clickhouse_string(uuid), f"toUUIDOrNull('{str(uuid)}')")
        date = datetime.fromisoformat("2020-02-02 02:02:02")
        self.assertEqual(
            escape_clickhouse_string(date),
            "toDateTime64('2020-02-02 02:02:02.000000', 6, 'UTC')",
        )
        self.assertEqual(
            escape_clickhouse_string(date, timezone="Europe/Brussels"),
            "toDateTime64('2020-02-02 03:02:02.000000', 6, 'Europe/Brussels')",
        )
        self.assertEqual(escape_clickhouse_string(date.date()), "toDate('2020-02-02')")
        self.assertEqual(escape_clickhouse_string(1), "1")
        self.assertEqual(escape_clickhouse_string(-1), "-1")
        self.assertEqual(escape_clickhouse_string(float("inf")), "Inf")
        self.assertEqual(escape_clickhouse_string(float("nan")), "NaN")
        self.assertEqual(escape_clickhouse_string(float("-inf")), "-Inf")
        self.assertEqual(escape_clickhouse_string(float("123")), "123.0")
        self.assertEqual(escape_clickhouse_string(float("123.123")), "123.123")
        self.assertEqual(escape_clickhouse_string(float("-123.123")), "-123.123")
        self.assertEqual(escape_clickhouse_string(float("0.000000000000000001")), "1e-18")
        self.assertEqual(
            escape_clickhouse_string(float("234732482374928374923")),
            "2.3473248237492837e+20",
        )

    def test_sanitize_hogql_string(self):
        self.assertEqual(escape_hogql_string("a"), "'a'")
        self.assertEqual(escape_hogql_string("$browser"), "'$browser'")
        self.assertEqual(escape_hogql_string("a b c"), "'a b c'")
        self.assertEqual(escape_hogql_string("a#$%#"), "'a#$%#'")
        self.assertEqual(escape_hogql_string("back`tick"), "'back`tick'")
        self.assertEqual(escape_hogql_string("single'quote"), "'single\\'quote'")
        self.assertEqual(escape_hogql_string('double"quote'), "'double\"quote'")
        self.assertEqual(
            escape_hogql_string("other escapes: \b \f \n \t \0 \a \v \\"),
            "'other escapes: \\b \\f \\n \\t \\0 \\a \\v \\\\'",
        )
        self.assertEqual(escape_hogql_string(["list", "things", []]), "['list', 'things', []]")
        self.assertEqual(escape_hogql_string(("tuple", "things", ())), "('tuple', 'things', ())")
        uuid = UUIDT()
        self.assertEqual(escape_hogql_string(uuid), f"toUUID('{str(uuid)}')")
        date = datetime.fromisoformat("2020-02-02 02:02:02")
        self.assertEqual(escape_hogql_string(date), "toDateTime('2020-02-02 02:02:02.000000')")
        self.assertEqual(
            escape_hogql_string(date, timezone="Europe/Brussels"),
            "toDateTime('2020-02-02 03:02:02.000000')",
        )
        self.assertEqual(escape_hogql_string(date.date()), "toDate('2020-02-02')")
        self.assertEqual(escape_hogql_string(1), "1")
        self.assertEqual(escape_hogql_string(-1), "-1")
        self.assertEqual(escape_hogql_string(float("inf")), "Inf")
        self.assertEqual(escape_hogql_string(float("nan")), "NaN")
        self.assertEqual(escape_hogql_string(float("-inf")), "-Inf")
        self.assertEqual(escape_hogql_string(float("123")), "123.0")
        self.assertEqual(escape_hogql_string(float("123.123")), "123.123")
        self.assertEqual(escape_hogql_string(float("-123.123")), "-123.123")
        self.assertEqual(escape_hogql_string(float("0.000000000000000001")), "1e-18")
        self.assertEqual(
            escape_hogql_string(float("234732482374928374923")),
            "2.3473248237492837e+20",
        )

    def test_escape_hogql_identifier_errors(self):
        with self.assertRaises(QueryError) as context:
            escape_hogql_identifier("with % percent")
        self.assertTrue(
            'The HogQL identifier "with % percent" is not permitted as it contains the "%" character'
            in str(context.exception)
        )

    def test_escape_clickhouse_identifier_errors(self):
        with self.assertRaises(QueryError) as context:
            escape_clickhouse_identifier("with % percent")
        self.assertTrue(
            'The HogQL identifier "with % percent" is not permitted as it contains the "%" character'
            in str(context.exception)
        )

    def test_escape_clickhouse_string_errors(self):
        # This test is a stopgap. Think long and hard before adding support for printing dicts or objects.
        # Make sure string escaping happens at the right level, and % is tested through and through.
        with self.assertRaises(ResolutionError) as context:
            escape_clickhouse_string({"a": 1, "b": 2})  # type: ignore
        self.assertTrue("SQLValueEscaper has no method visit_dict" in str(context.exception))


class TestClickHouseIdentifierExecution(ClickhouseTestMixin, BaseTest):
    @parameterized.expand([(f"sample-{i}", sample) for i, sample in enumerate(_ROUNDTRIP_IDENTIFIER_SAMPLES)])
    def test_escaped_identifier_round_trips_through_clickhouse(self, _name, identifier):
        # ClickHouse, not just the HogQL parser, is the real consumer of escape_clickhouse_identifier:
        # it must parse the escaped alias and report the original name back.
        escaped = escape_clickhouse_identifier(identifier)
        _, columns = sync_execute(f"SELECT 1 AS {escaped}", with_column_types=True)
        self.assertEqual(columns[0][0], identifier)
