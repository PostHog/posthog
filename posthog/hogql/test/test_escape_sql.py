from datetime import datetime

from posthog.test.base import BaseTest

from posthog.hogql.errors import QueryError, ResolutionError
from posthog.hogql.escape_sql import (
    escape_clickhouse_identifier,
    escape_clickhouse_string,
    escape_hogql_identifier,
    escape_hogql_string,
)

from posthog.models.utils import UUIDT


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
        self.assertEqual(escape_hogql_identifier("back`tick"), "`back\\`tick`")
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
        self.assertEqual(escape_clickhouse_identifier("back`tick"), "`back\\`tick`")
        self.assertEqual(escape_clickhouse_identifier("single'quote"), "`single'quote`")
        self.assertEqual(escape_clickhouse_identifier('double"quote'), '`double"quote`')
        self.assertEqual(
            escape_clickhouse_identifier("other escapes: \b \f \n \t \0 \a \v \\"),
            "`other escapes: \\b \\f \\n \\t \\0 \\a \\v \\\\`",
        )

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
