"""Lay out a query on several lines, so a person can read it in the new metric form.

Only whitespace changes. A layout that parses to a different query keeps the original text.
"""

import re

import sqlparse
from sqlparse.exceptions import SQLParseError

from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_select

# Layout takes time in proportion to length, and a query this long is rare and unreadable either way.
_MAX_FORMAT_CHARS = 10000
# sqlparse puts each item of a long value list on its own padded line, which can grow the text a hundredfold.
# A short query with many short columns can double in length too, but it stays small, so the floor lets it through.
_MAX_GROWTH = 2
_GROWTH_FLOOR_CHARS = 2000
_WHITESPACE = re.compile(r"\s+")


def readable_sql(sql: str) -> str:
    if not sql or len(sql) > _MAX_FORMAT_CHARS:
        return sql
    try:
        # Keyword case stays as written: HogQL names such as `month` or `events` are case-sensitive.
        formatted = sqlparse.format(sql, reindent=True, indent_width=4).strip()
    except SQLParseError:
        # sqlparse stops at a fixed nesting depth, such as a hundred nested function calls.
        return sql
    if len(formatted) > max(_MAX_GROWTH * len(sql), _GROWTH_FLOOR_CHARS):
        return sql
    try:
        unchanged = parse_select(formatted).to_hogql() == parse_select(sql).to_hogql()
    except BaseHogQLError:
        # A dashboard placeholder such as {filters} does not parse, so check that only whitespace moved.
        unchanged = _WHITESPACE.sub("", formatted) == _WHITESPACE.sub("", sql)
    return formatted if unchanged else sql
