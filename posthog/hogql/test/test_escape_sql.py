from datetime import datetime

from posthog.test.base import BaseTest

from posthog.hogql.errors import QueryError, ResolutionError
from posthog.hogql.escape_sql import (
    escape_clickhouse_identifier,
    escape_clickhouse_string,
    escape_hogql_identifier,
    escape_hogql_string,
    escape_postgres_identifier,
)

from posthog.clickhouse.client.escape import substitute_params
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

    def test_escape_hogql_identifier_with_percent(self):
        # HogQL output is not run through printf-style parameter substitution, so the
        # ``%`` is emitted as-is inside backquotes — the HogQL parser accepts it literally.
        self.assertEqual(escape_hogql_identifier("with % percent"), "`with % percent`")
        self.assertEqual(escape_hogql_identifier("col%name"), "`col%name`")
        self.assertEqual(escape_hogql_identifier("100%"), "`100%`")

    def test_escape_clickhouse_identifier_with_percent(self):
        # ClickHouse SQL is rendered via ``query % params``, so any literal ``%`` inside a
        # backquoted identifier must be doubled to ``%%`` at the print boundary so it survives
        # the substitution and lands as a single ``%`` in the final SQL sent to ClickHouse.
        self.assertEqual(escape_clickhouse_identifier("with % percent"), "`with %% percent`")
        self.assertEqual(escape_clickhouse_identifier("col%name"), "`col%%name`")
        self.assertEqual(escape_clickhouse_identifier("100%"), "`100%%`")

    def test_escape_clickhouse_identifier_percent_survives_substitution(self):
        # End-to-end check: the doubled ``%%`` must collapse back to ``%`` after the
        # clickhouse-driver substitution stage that real queries flow through.
        escaped = escape_clickhouse_identifier("col%name")
        # Embed in a SELECT alongside a parameter so substitute_params actually runs.
        rendered = substitute_params(f"SELECT {escaped} FROM events WHERE team_id = %(team)s", {"team": 1})
        self.assertEqual(rendered, "SELECT `col%name` FROM events WHERE team_id = 1")

    def test_escape_clickhouse_string_errors(self):
        # This test is a stopgap. Think long and hard before adding support for printing dicts or objects.
        # Make sure string escaping happens at the right level, and % is tested through and through.
        with self.assertRaises(ResolutionError) as context:
            escape_clickhouse_string({"a": 1, "b": 2})  # type: ignore
        self.assertTrue("SQLValueEscaper has no method visit_dict" in str(context.exception))
