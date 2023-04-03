from datetime import datetime

from posthog.hogql.print_string import (
    print_hogql_identifier,
    print_clickhouse_string,
    print_clickhouse_identifier,
    print_hogql_string,
)
from posthog.models.utils import UUIDT
from posthog.test.base import BaseTest


class TestPrintString(BaseTest):
    def test_sanitize_hogql_identifier(self):
        self.assertEqual(print_hogql_identifier("a"), "a")
        self.assertEqual(print_hogql_identifier("$browser"), "$browser")
        self.assertEqual(print_hogql_identifier("event"), "event")
        self.assertEqual(print_hogql_identifier("a b c"), "`a b c`")
        self.assertEqual(print_hogql_identifier("a.b.c"), "`a.b.c`")
        self.assertEqual(print_hogql_identifier("a-b-c"), "`a-b-c`")
        self.assertEqual(print_hogql_identifier("a#$%#"), "`a#$%#`")
        self.assertEqual(print_hogql_identifier("back`tick"), "`back\\`tick`")
        self.assertEqual(print_hogql_identifier("single'quote"), "`single'quote`")
        self.assertEqual(print_hogql_identifier('double"quote'), '`double"quote`')
        self.assertEqual(
            print_hogql_identifier("other escapes: \b \f \n \t \0 \a \v \\"),
            "`other escapes: \\b \\f \\n \\t \\0 \\a \\v \\\\`",
        )

    def test_sanitize_clickhouse_identifier(self):
        self.assertEqual(print_clickhouse_identifier("a"), "a")
        self.assertEqual(print_clickhouse_identifier("$browser"), "`$browser`")
        self.assertEqual(print_clickhouse_identifier("event"), "event")
        self.assertEqual(print_clickhouse_identifier("a b c"), "`a b c`")
        self.assertEqual(print_clickhouse_identifier("a.b.c"), "`a.b.c`")
        self.assertEqual(print_clickhouse_identifier("a-b-c"), "`a-b-c`")
        self.assertEqual(print_clickhouse_identifier("a#$%#"), "`a#$%#`")
        self.assertEqual(print_clickhouse_identifier("back`tick"), "`back\\`tick`")
        self.assertEqual(print_clickhouse_identifier("single'quote"), "`single'quote`")
        self.assertEqual(print_clickhouse_identifier('double"quote'), '`double"quote`')
        self.assertEqual(
            print_clickhouse_identifier("other escapes: \b \f \n \t \0 \a \v \\"),
            "`other escapes: \\b \\f \\n \\t \\0 \\a \\v \\\\`",
        )

    def test_sanitize_clickhouse_string(self):
        self.assertEqual(print_clickhouse_string("a"), "'a'")
        self.assertEqual(print_clickhouse_string("$browser"), "'$browser'")
        self.assertEqual(print_clickhouse_string("a b c"), "'a b c'")
        self.assertEqual(print_clickhouse_string("a#$%#"), "'a#$%#'")
        self.assertEqual(print_clickhouse_string("back`tick"), "'back`tick'")
        self.assertEqual(print_clickhouse_string("single'quote"), "'single\\'quote'")
        self.assertEqual(print_clickhouse_string('double"quote'), "'double\"quote'")
        self.assertEqual(
            print_clickhouse_string("other escapes: \b \f \n \t \0 \a \v \\"),
            "'other escapes: \\b \\f \\n \\t \\0 \\a \\v \\\\'",
        )
        self.assertEqual(print_clickhouse_string(["list", "things", []]), "['list', 'things', []]")
        self.assertEqual(print_clickhouse_string(("tuple", "things", ())), "('tuple', 'things', ())")
        uuid = UUIDT()
        self.assertEqual(print_clickhouse_string(uuid), f"'{str(uuid)}'")
        date = datetime.fromisoformat("2020-02-02 02:02:02")
        self.assertEqual(print_clickhouse_string(date), "toDateTime('2020-02-02 02:02:02', 'UTC')")
        self.assertEqual(
            print_clickhouse_string(date, timezone="Europe/Brussels"),
            "toDateTime('2020-02-02 03:02:02', 'Europe/Brussels')",
        )
        self.assertEqual(print_clickhouse_string(date.date()), "toDate('2020-02-02')")

    def test_sanitize_hogql_string(self):
        self.assertEqual(print_hogql_string("a"), "'a'")
        self.assertEqual(print_hogql_string("$browser"), "'$browser'")
        self.assertEqual(print_hogql_string("a b c"), "'a b c'")
        self.assertEqual(print_hogql_string("a#$%#"), "'a#$%#'")
        self.assertEqual(print_hogql_string("back`tick"), "'back`tick'")
        self.assertEqual(print_hogql_string("single'quote"), "'single\\'quote'")
        self.assertEqual(print_hogql_string('double"quote'), "'double\"quote'")
        self.assertEqual(
            print_hogql_string("other escapes: \b \f \n \t \0 \a \v \\"),
            "'other escapes: \\b \\f \\n \\t \\0 \\a \\v \\\\'",
        )
        self.assertEqual(print_hogql_string(["list", "things", []]), "['list', 'things', []]")
        self.assertEqual(print_hogql_string(("tuple", "things", ())), "('tuple', 'things', ())")
        uuid = UUIDT()
        self.assertEqual(print_hogql_string(uuid), f"'{str(uuid)}'")
        date = datetime.fromisoformat("2020-02-02 02:02:02")
        self.assertEqual(print_hogql_string(date), "toDateTime('2020-02-02 02:02:02')")
        self.assertEqual(print_hogql_string(date, timezone="Europe/Brussels"), "toDateTime('2020-02-02 03:02:02')")
        self.assertEqual(print_hogql_string(date.date()), "toDate('2020-02-02')")
