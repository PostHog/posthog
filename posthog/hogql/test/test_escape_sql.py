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
import pytest


class TestPrintString(BaseTest):
    def test_sanitize_hogql_identifier(self):
        assert escape_hogql_identifier("a") == "a"
        assert escape_hogql_identifier("$browser") == "$browser"
        assert escape_hogql_identifier("0asd") == "`0asd`"
        assert escape_hogql_identifier("123") == "`123`"
        assert escape_hogql_identifier("event") == "event"
        assert escape_hogql_identifier("a b c") == "`a b c`"
        assert escape_hogql_identifier("a.b.c") == "`a.b.c`"
        assert escape_hogql_identifier("a-b-c") == "`a-b-c`"
        assert escape_hogql_identifier("a#$#") == "`a#$#`"
        assert escape_hogql_identifier("back`tick") == "`back\\`tick`"
        assert escape_hogql_identifier("single'quote") == "`single'quote`"
        assert escape_hogql_identifier('double"quote') == '`double"quote`'
        assert escape_hogql_identifier("other escapes: \x08 \x0c \n \t \x00 \x07 \x0b \\") == "`other escapes: \\b \\f \\n \\t \\0 \\a \\v \\\\`"

    def test_sanitize_clickhouse_identifier(self):
        assert escape_clickhouse_identifier("a") == "a"
        assert escape_clickhouse_identifier("$browser") == "`$browser`"
        assert escape_clickhouse_identifier("0asd") == "`0asd`"
        assert escape_clickhouse_identifier("123") == "`123`"
        assert escape_clickhouse_identifier("event") == "event"
        assert escape_clickhouse_identifier("a b c") == "`a b c`"
        assert escape_clickhouse_identifier("a.b.c") == "`a.b.c`"
        assert escape_clickhouse_identifier("a-b-c") == "`a-b-c`"
        assert escape_clickhouse_identifier("a#$#") == "`a#$#`"
        assert escape_clickhouse_identifier("back`tick") == "`back\\`tick`"
        assert escape_clickhouse_identifier("single'quote") == "`single'quote`"
        assert escape_clickhouse_identifier('double"quote') == '`double"quote`'
        assert escape_clickhouse_identifier("other escapes: \x08 \x0c \n \t \x00 \x07 \x0b \\") == "`other escapes: \\b \\f \\n \\t \\0 \\a \\v \\\\`"

    def test_sanitize_clickhouse_string(self):
        assert escape_clickhouse_string("a") == "'a'"
        assert escape_clickhouse_string("$browser") == "'$browser'"
        assert escape_clickhouse_string("a b c") == "'a b c'"
        assert escape_clickhouse_string("a#$%#") == "'a#$%#'"
        assert escape_clickhouse_string("back`tick") == "'back`tick'"
        assert escape_clickhouse_string("single'quote") == "'single\\'quote'"
        assert escape_clickhouse_string('double"quote') == "'double\"quote'"
        assert escape_clickhouse_string("other escapes: \x08 \x0c \n \t \x00 \x07 \x0b \\") == "'other escapes: \\b \\f \\n \\t \\0 \\a \\v \\\\'"
        assert escape_clickhouse_string(["list", "things", []]) == "['list', 'things', []]"
        assert escape_clickhouse_string(("tuple", "things", ())) == "('tuple', 'things', ())"
        uuid = UUIDT()
        assert escape_clickhouse_string(uuid) == f"toUUIDOrNull('{str(uuid)}')"
        date = datetime.fromisoformat("2020-02-02 02:02:02")
        assert escape_clickhouse_string(date) == "toDateTime64('2020-02-02 02:02:02.000000', 6, 'UTC')"
        assert escape_clickhouse_string(date, timezone="Europe/Brussels") == "toDateTime64('2020-02-02 03:02:02.000000', 6, 'Europe/Brussels')"
        assert escape_clickhouse_string(date.date()) == "toDate('2020-02-02')"
        assert escape_clickhouse_string(1) == "1"
        assert escape_clickhouse_string(-1) == "-1"
        assert escape_clickhouse_string(float("inf")) == "Inf"
        assert escape_clickhouse_string(float("nan")) == "NaN"
        assert escape_clickhouse_string(float("-inf")) == "-Inf"
        assert escape_clickhouse_string(float("123")) == "123.0"
        assert escape_clickhouse_string(float("123.123")) == "123.123"
        assert escape_clickhouse_string(float("-123.123")) == "-123.123"
        assert escape_clickhouse_string(float("0.000000000000000001")) == "1e-18"
        assert escape_clickhouse_string(float("234732482374928374923")) == "2.3473248237492837e+20"

    def test_sanitize_hogql_string(self):
        assert escape_hogql_string("a") == "'a'"
        assert escape_hogql_string("$browser") == "'$browser'"
        assert escape_hogql_string("a b c") == "'a b c'"
        assert escape_hogql_string("a#$%#") == "'a#$%#'"
        assert escape_hogql_string("back`tick") == "'back`tick'"
        assert escape_hogql_string("single'quote") == "'single\\'quote'"
        assert escape_hogql_string('double"quote') == "'double\"quote'"
        assert escape_hogql_string("other escapes: \x08 \x0c \n \t \x00 \x07 \x0b \\") == "'other escapes: \\b \\f \\n \\t \\0 \\a \\v \\\\'"
        assert escape_hogql_string(["list", "things", []]) == "['list', 'things', []]"
        assert escape_hogql_string(("tuple", "things", ())) == "('tuple', 'things', ())"
        uuid = UUIDT()
        assert escape_hogql_string(uuid) == f"toUUID('{str(uuid)}')"
        date = datetime.fromisoformat("2020-02-02 02:02:02")
        assert escape_hogql_string(date) == "toDateTime('2020-02-02 02:02:02.000000')"
        assert escape_hogql_string(date, timezone="Europe/Brussels") == "toDateTime('2020-02-02 03:02:02.000000')"
        assert escape_hogql_string(date.date()) == "toDate('2020-02-02')"
        assert escape_hogql_string(1) == "1"
        assert escape_hogql_string(-1) == "-1"
        assert escape_hogql_string(float("inf")) == "Inf"
        assert escape_hogql_string(float("nan")) == "NaN"
        assert escape_hogql_string(float("-inf")) == "-Inf"
        assert escape_hogql_string(float("123")) == "123.0"
        assert escape_hogql_string(float("123.123")) == "123.123"
        assert escape_hogql_string(float("-123.123")) == "-123.123"
        assert escape_hogql_string(float("0.000000000000000001")) == "1e-18"
        assert escape_hogql_string(float("234732482374928374923")) == "2.3473248237492837e+20"

    def test_escape_hogql_identifier_errors(self):
        with pytest.raises(QueryError) as context:
            escape_hogql_identifier("with % percent")
        assert 'The HogQL identifier "with % percent" is not permitted as it contains the "%" character' in str(context.value)

    def test_escape_clickhouse_identifier_errors(self):
        with pytest.raises(QueryError) as context:
            escape_clickhouse_identifier("with % percent")
        assert 'The HogQL identifier "with % percent" is not permitted as it contains the "%" character' in str(context.value)

    def test_escape_clickhouse_string_errors(self):
        # This test is a stopgap. Think long and hard before adding support for printing dicts or objects.
        # Make sure string escaping happens at the right level, and % is tested through and through.
        with pytest.raises(ResolutionError) as context:
            escape_clickhouse_string({"a": 1, "b": 2})  # type: ignore
        assert "SQLValueEscaper has no method visit_dict" in str(context.value)
