import re
from datetime import datetime
from typing import Optional

import pytz

# Copied from clickhouse_driver.util.escape, adapted only from single quotes to backquotes.
escape_chars_map = {
    "\b": "\\b",
    "\f": "\\f",
    "\r": "\\r",
    "\n": "\\n",
    "\t": "\\t",
    "\0": "\\0",
    "\a": "\\a",
    "\v": "\\v",
    "\\": "\\\\",
}
string_escape_chars_map = {**escape_chars_map, "'": "\\'"}
backquote_escape_chars_map = {
    **escape_chars_map,
    "`": "\\`",
}


# Copied from clickhouse_driver.util.escape, adapted from single quotes to backquotes. Added a $.
def print_hogql_identifier(identifier: str) -> str:
    # HogQL allows dollars in the identifier.
    if re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", identifier):
        return identifier

    return "`%s`" % "".join(backquote_escape_chars_map.get(c, c) for c in identifier)


# Copied from clickhouse_driver.util.escape, adapted from single quotes to backquotes.
def print_clickhouse_identifier(identifier: str) -> str:
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", identifier):
        return identifier

    return "`%s`" % "".join(backquote_escape_chars_map.get(c, c) for c in identifier)


# Copied from clickhouse_driver.util.escape_param
def print_clickhouse_string(name: str | list | tuple | datetime, timezone: Optional[str] = None) -> str:
    if isinstance(name, list):
        return "[%s]" % ", ".join(str(print_clickhouse_string(x)) for x in name)
    elif isinstance(name, tuple):
        return "(%s)" % ", ".join(str(print_clickhouse_string(x)) for x in name)
    elif isinstance(name, datetime):
        datetime_string_in_timezone = name.astimezone(pytz.timezone(timezone or "UTC")).strftime("%Y-%m-%d %H:%M:%S")
        return f"toDateTime({print_clickhouse_string(datetime_string_in_timezone)}, {print_clickhouse_string(timezone or 'UTC')})"
    return "'%s'" % "".join(string_escape_chars_map.get(c, c) for c in name)
