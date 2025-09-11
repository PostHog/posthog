import re
import math
from datetime import date, datetime
from typing import Any, Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from posthog.hogql.errors import QueryError, ResolutionError

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
singlequote_escape_chars_map = {**escape_chars_map, "'": "\\'"}
backquote_escape_chars_map = {**escape_chars_map, "`": "\\`"}


def safe_identifier(identifier: str) -> str:
    if "%" in identifier:
        identifier = identifier.replace("%", "")

    return identifier


# Copied from clickhouse_driver.util.escape_param
def escape_param_clickhouse(value: str) -> str:
    return "'{}'".format("".join(singlequote_escape_chars_map.get(c, c) for c in str(value)))


# Copied from clickhouse_driver.util.escape, adapted from single quotes to backquotes. Added a $.
def escape_hogql_identifier(identifier: str | int) -> str:
    if isinstance(identifier, int):  # In HogQL we allow integers as identifiers to access array elements
        return str(identifier)
    if "%" in identifier:
        raise QueryError(f'The HogQL identifier "{identifier}" is not permitted as it contains the "%" character')
    # HogQL allows dollars in the identifier.
    if re.match(
        r"^[A-Za-z_$][A-Za-z0-9_$]*$", identifier
    ):  # Same regex as the frontend escapePropertyAsHogQlIdentifier
        return identifier
    return "`{}`".format("".join(backquote_escape_chars_map.get(c, c) for c in identifier))


# Copied from clickhouse_driver.util.escape, adapted from single quotes to backquotes.
def escape_clickhouse_identifier(identifier: str) -> str:
    if "%" in identifier:
        raise QueryError(f'The HogQL identifier "{identifier}" is not permitted as it contains the "%" character')
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", identifier):
        return identifier
    return "`{}`".format("".join(backquote_escape_chars_map.get(c, c) for c in identifier))


def escape_hogql_string(
    name: float | int | str | list | tuple | date | datetime | UUID | UUIDT,
    timezone: Optional[str] = None,
) -> str:
    return SQLValueEscaper(timezone=timezone, dialect="hogql").visit(name)


def escape_clickhouse_string(
    name: Optional[float | int | str | list | tuple | date | datetime | UUID | UUIDT],
    timezone: Optional[str] = None,
) -> str:
    return SQLValueEscaper(timezone=timezone, dialect="clickhouse").visit(name)


class SQLValueEscaper:
    def __init__(
        self,
        timezone: Optional[str] = None,
        dialect: Literal["hogql", "clickhouse"] = "clickhouse",
    ):
        self._timezone = timezone or "UTC"
        self._dialect = dialect

    # Unlike posthog.hogql.visitor.Visitor, this tiny visitor works on primitives.
    def visit(self, node: Any) -> str:
        method_name = f"visit_{node.__class__.__name__.lower()}"
        if hasattr(self, method_name):
            return getattr(self, method_name)(node)
        raise ResolutionError(f"SQLValueEscaper has no method {method_name}")

    def visit_nonetype(self, value: None):
        return "NULL"

    def visit_str(self, value: str):
        return escape_param_clickhouse(value)

    def visit_bool(self, value: bool):
        if self._dialect == "clickhouse":
            return "1" if value is True else "0"
        return "true" if value is True else "false"

    def visit_int(self, value: int):
        return str(value)

    def visit_float(self, value: float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            if value == float("-inf"):
                return "-Inf"
            return "Inf"
        return str(value)

    def visit_uuid(self, value: UUID):
        if self._dialect == "hogql":
            return f"toUUID({self.visit(str(value))})"
        return f"toUUIDOrNull({self.visit(str(value))})"

    def visit_uuidt(self, value: UUIDT):
        if self._dialect == "hogql":
            return f"toUUID({self.visit(str(value))})"
        return f"toUUIDOrNull({self.visit(str(value))})"

    def visit_fakedatetime(self, value: datetime):
        return self.visit_datetime(value)

    def visit_datetime(self, value: datetime):
        datetime_string = value.astimezone(ZoneInfo(self._timezone)).strftime("%Y-%m-%d %H:%M:%S.%f")
        if self._dialect == "hogql":
            return f"toDateTime({self.visit(datetime_string)})"  # no timezone for hogql
        return f"toDateTime64({self.visit(datetime_string)}, 6, {self.visit(self._timezone)})"

    def visit_fakedate(self, value: date):
        return self.visit_date(value)

    def visit_date(self, value: date):
        return f"toDate({self.visit(value.strftime('%Y-%m-%d'))})"

    def visit_list(self, value: list):
        return f"[{', '.join(str(self.visit(x)) for x in value)}]"

    def visit_tuple(self, value: tuple):
        return f"({', '.join(str(self.visit(x)) for x in value)})"
