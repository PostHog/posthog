import re
from datetime import datetime, date
from typing import Optional, Any, Literal, List, Tuple
from uuid import UUID

import pytz

from posthog.models.utils import UUIDT

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


def print_hogql_string(name: str | list | tuple | date | datetime | UUID, timezone: Optional[str] = None) -> str:
    return SQLValueEscaper(timezone=timezone, dialect="hogql").visit(name)


def print_clickhouse_string(name: str | list | tuple | date | datetime | UUID, timezone: Optional[str] = None) -> str:
    return SQLValueEscaper(timezone=timezone, dialect="clickhouse").visit(name)


class SQLValueEscaper:
    def __init__(self, timezone: Optional[str] = None, dialect: Literal["hogql", "clickhouse"] = "clickhouse"):
        self._timezone = timezone or "UTC"
        self._dialect = dialect

    def visit(self, node: Any) -> str:
        # This tiny visitor works on primitives, unlike posthog.hogql.visitor.Visitor
        method_name = f"visit_{node.__class__.__name__.lower()}"
        if hasattr(self, method_name):
            return getattr(self, method_name)(node)
        raise ValueError(f"SQLValueEscaper has no method {method_name}")

    def visit_nonetype(self, value: None):
        return "NULL"

    def visit_str(self, value: str):
        # Copied from clickhouse_driver.util.escape_param
        return "'%s'" % "".join(string_escape_chars_map.get(c, c) for c in str(value))

    def visit_uuid(self, value: UUID):
        if self._dialect == "hogql":
            return f"toUUID({self.visit(str(value))})"
        return f"toUUIDOrNull({self.visit(str(value))})"

    def visit_uuidt(self, value: UUIDT):
        if self._dialect == "hogql":
            return f"toUUID({self.visit(str(value))})"
        return f"toUUIDOrNull({self.visit(str(value))})"

    def visit_fakedatetime(self, value: datetime):
        self.visit_datetime(value)

    def visit_datetime(self, value: datetime):
        datetime_string = value.astimezone(pytz.timezone(self._timezone)).strftime("%Y-%m-%d %H:%M:%S")
        if self._dialect == "hogql":
            return f"toDateTime({self.visit(datetime_string)})"  # no timezone for hogql
        return f"toDateTime({self.visit(datetime_string)}, {self.visit(self._timezone)})"

    def visit_date(self, value: date):
        return f"toDate({self.visit(value.strftime('%Y-%m-%d'))})"

    def visit_list(self, value: List):
        return f"[{', '.join(str(self.visit(x)) for x in value)}]"

    def visit_tuple(self, value: Tuple):
        return f"({', '.join(str(self.visit(x)) for x in value)})"
