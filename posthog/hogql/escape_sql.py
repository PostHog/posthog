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
# The HogQL/ClickHouse parsers only accept a doubled backtick inside a quoted identifier, not a backslash-escaped one.
backquote_escape_chars_map = {**escape_chars_map, "`": "``"}


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


# Copied from dlt/common/data_writers/escape.py
POSTGRES_SIMPLE_IDENTIFIER_REGEX = re.compile(r"^[a-z_][a-z0-9_$]*$")

# https://www.postgresql.org/docs/current/sql-keywords-appendix.html
POSTGRES_RESERVED_KEYWORDS = {
    "ALL",
    "ANALYSE",
    "ANALYZE",
    "AND",
    "ANY",
    "ARRAY",
    "AS",
    "ASC",
    "ASYMMETRIC",
    "AUTHORIZATION",
    "BINARY",
    "BOTH",
    "CASE",
    "CAST",
    "CHECK",
    "COLLATE",
    "COLLATION",
    "COLUMN",
    "CONCURRENTLY",
    "CONSTRAINT",
    "CREATE",
    "CROSS",
    "CURRENT_CATALOG",
    "CURRENT_DATE",
    "CURRENT_ROLE",
    "CURRENT_SCHEMA",
    "CURRENT_TIME",
    "CURRENT_TIMESTAMP",
    "CURRENT_USER",
    "DEFAULT",
    "DEFERRABLE",
    "DESC",
    "DISTINCT",
    "DO",
    "ELSE",
    "END",
    "EXCEPT",
    "FALSE",
    "FETCH",
    "FOR",
    "FOREIGN",
    "FREEZE",
    "FROM",
    "FULL",
    "GRANT",
    "GROUP",
    "HAVING",
    "ILIKE",
    "IN",
    "INITIALLY",
    "INNER",
    "INTERSECT",
    "INTO",
    "IS",
    "ISNULL",
    "JOIN",
    "LATERAL",
    "LEADING",
    "LEFT",
    "LIKE",
    "LIMIT",
    "LOCALTIME",
    "LOCALTIMESTAMP",
    "NATURAL",
    "NOT",
    "NOTNULL",
    "NULL",
    "OFFSET",
    "ON",
    "ONLY",
    "OR",
    "ORDER",
    "OUTER",
    "OVER",
    "OVERLAPS",
    "PLACING",
    "PRIMARY",
    "REFERENCES",
    "RETURNING",
    "RIGHT",
    "SELECT",
    "SESSION_USER",
    "SIMILAR",
    "SOME",
    "SYMMETRIC",
    "TABLE",
    "TABLESAMPLE",
    "THEN",
    "TO",
    "TRAILING",
    "TRUE",
    "UNION",
    "UNIQUE",
    "USER",
    "USING",
    "VARIADIC",
    "VERBOSE",
    "WHEN",
    "WHERE",
    "WINDOW",
    "WITH",
}


# DuckDB reserves a handful of additional keywords that Postgres doesn't, so identifiers
# colliding with these must be quoted when emitting DuckDB SQL even though they'd be
# unambiguous in Postgres. Derived from DuckDB's ``duckdb_keywords()`` catalog with
# ``keyword_category = 'reserved'`` — re-verify and update before major DuckDB version bumps.
DUCKDB_EXTRA_RESERVED_KEYWORDS = {
    "ANTI",
    "ASOF",
    "ATTACH",
    "DETACH",
    "EXCLUDE",
    "INSTALL",
    "LOAD",
    "MACRO",
    "PIVOT",
    "POSITIONAL",
    "PRAGMA",
    "QUALIFY",
    "REPLACE",
    "SAMPLE",
    "SEMI",
    "SUMMARIZE",
    "UNPIVOT",
}


# Simple lowercase identifiers can stay unquoted; everything else is backtick-quoted
# unless rejected by escape_mysql_identifier's hard exclusions.
MYSQL_SIMPLE_IDENTIFIER_REGEX = re.compile(r"^[a-z_][a-z0-9_$]*$")


# https://dev.mysql.com/doc/refman/8.0/en/keywords.html — reserved words only (not the full
# keyword list). Identifiers colliding with these must be backtick-quoted.
MYSQL_RESERVED_KEYWORDS = {
    "ACCESSIBLE", "ADD", "ALL", "ALTER", "ANALYZE", "AND", "AS", "ASC", "ASENSITIVE",
    "BEFORE", "BETWEEN", "BIGINT", "BINARY", "BLOB", "BOTH", "BY",
    "CALL", "CASCADE", "CASE", "CHANGE", "CHAR", "CHARACTER", "CHECK", "COLLATE", "COLUMN",
    "CONDITION", "CONSTRAINT", "CONTINUE", "CONVERT", "CREATE", "CROSS", "CUBE", "CUME_DIST",
    "CURRENT_DATE", "CURRENT_TIME", "CURRENT_TIMESTAMP", "CURRENT_USER", "CURSOR",
    "DATABASE", "DATABASES", "DAY_HOUR", "DAY_MICROSECOND", "DAY_MINUTE", "DAY_SECOND",
    "DEC", "DECIMAL", "DECLARE", "DEFAULT", "DELAYED", "DELETE", "DENSE_RANK", "DESC",
    "DESCRIBE", "DETERMINISTIC", "DISTINCT", "DISTINCTROW", "DIV", "DOUBLE", "DROP", "DUAL",
    "EACH", "ELSE", "ELSEIF", "EMPTY", "ENCLOSED", "ESCAPED", "EXCEPT", "EXISTS", "EXIT",
    "EXPLAIN", "FALSE", "FETCH", "FIRST_VALUE", "FLOAT", "FLOAT4", "FLOAT8", "FOR", "FORCE",
    "FOREIGN", "FROM", "FULLTEXT", "FUNCTION",
    "GENERATED", "GET", "GRANT", "GROUP", "GROUPING", "GROUPS",
    "HAVING", "HIGH_PRIORITY", "HOUR_MICROSECOND", "HOUR_MINUTE", "HOUR_SECOND",
    "IF", "IGNORE", "IN", "INDEX", "INFILE", "INNER", "INOUT", "INSENSITIVE", "INSERT",
    "INT", "INT1", "INT2", "INT3", "INT4", "INT8", "INTEGER", "INTERSECT", "INTERVAL",
    "INTO", "IO_AFTER_GTIDS", "IO_BEFORE_GTIDS", "IS", "ITERATE",
    "JOIN", "JSON_TABLE", "KEY", "KEYS", "KILL",
    "LAG", "LAST_VALUE", "LATERAL", "LEAD", "LEADING", "LEAVE", "LEFT", "LIKE", "LIMIT",
    "LINEAR", "LINES", "LOAD", "LOCALTIME", "LOCALTIMESTAMP", "LOCK", "LONG", "LONGBLOB",
    "LONGTEXT", "LOOP", "LOW_PRIORITY",
    "MASTER_BIND", "MASTER_SSL_VERIFY_SERVER_CERT", "MATCH", "MAXVALUE", "MEDIUMBLOB",
    "MEDIUMINT", "MEDIUMTEXT", "MIDDLEINT", "MINUTE_MICROSECOND", "MINUTE_SECOND", "MOD",
    "MODIFIES", "NATURAL", "NOT", "NO_WRITE_TO_BINLOG", "NTH_VALUE", "NTILE", "NULL", "NUMERIC",
    "OF", "ON", "OPTIMIZE", "OPTIMIZER_COSTS", "OPTION", "OPTIONALLY", "OR", "ORDER", "OUT",
    "OUTER", "OUTFILE", "OVER",
    "PARTITION", "PERCENT_RANK", "PRECISION", "PRIMARY", "PROCEDURE", "PURGE",
    "RANGE", "RANK", "READ", "READS", "READ_WRITE", "REAL", "RECURSIVE", "REFERENCES",
    "REGEXP", "RELEASE", "RENAME", "REPEAT", "REPLACE", "REQUIRE", "RESIGNAL", "RESTRICT",
    "RETURN", "REVOKE", "RIGHT", "RLIKE", "ROW", "ROWS", "ROW_NUMBER",
    "SCHEMA", "SCHEMAS", "SECOND_MICROSECOND", "SELECT", "SENSITIVE", "SEPARATOR", "SET",
    "SHOW", "SIGNAL", "SMALLINT", "SPATIAL", "SPECIFIC", "SQL", "SQLEXCEPTION", "SQLSTATE",
    "SQLWARNING", "SQL_BIG_RESULT", "SQL_CALC_FOUND_ROWS", "SQL_SMALL_RESULT", "SSL",
    "STARTING", "STORED", "STRAIGHT_JOIN", "SYSTEM",
    "TABLE", "TERMINATED", "THEN", "TINYBLOB", "TINYINT", "TINYTEXT", "TO", "TRAILING",
    "TRIGGER", "TRUE",
    "UNDO", "UNION", "UNIQUE", "UNLOCK", "UNSIGNED", "UPDATE", "USAGE", "USE", "USING",
    "UTC_DATE", "UTC_TIME", "UTC_TIMESTAMP",
    "VALUES", "VARBINARY", "VARCHAR", "VARCHARACTER", "VARYING", "VIRTUAL",
    "WHEN", "WHERE", "WHILE", "WINDOW", "WITH", "WRITE",
    "XOR", "YEAR_MONTH", "ZEROFILL",
}  # fmt: skip


def escape_mysql_identifier(v: str) -> str:
    if len(v) > 64:
        raise QueryError(f'The MySQL identifier "{v}" is too long. Maximum length is 64 characters.')
    # MySQL allows almost anything inside backticks, but ``%`` would be interpreted
    # as a parameter placeholder by PyMySQL and NUL bytes are invalid identifiers.
    if "%" in v:
        raise QueryError(f'The MySQL identifier "{v}" is not permitted as it contains the "%" character')
    if "\0" in v:
        raise QueryError(f'The MySQL identifier "{v}" is not permitted as it contains a NUL character')

    # Always backtick-quote unless the identifier is a simple lowercase name. MySQL's reserved
    # word list is long and version-dependent, so quoting anything non-trivial is the safe default.
    if MYSQL_SIMPLE_IDENTIFIER_REGEX.match(v) and v.upper() not in MYSQL_RESERVED_KEYWORDS:
        return v
    return "`" + v.replace("`", "``") + "`"


def escape_postgres_identifier(v: str) -> str:
    if len(v) > 63:
        raise QueryError(f'The Postgres identifier "{v}" is too long. Maximum length is 63 characters.')

    return _quote_postgres_wire_identifier(v, extra_reserved_keywords=None)


def escape_duckdb_identifier(v: str) -> str:
    """Escape an identifier for DuckDB. Same quoting rules as Postgres but no length limit,
    and with DuckDB's additional reserved keywords treated as requiring quotes."""
    return _quote_postgres_wire_identifier(v, extra_reserved_keywords=DUCKDB_EXTRA_RESERVED_KEYWORDS)


def escape_snowflake_identifier(v: str) -> str:
    # Always double-quote: Snowflake folds unquoted identifiers to uppercase, so quoting
    # preserves the column's stored case. ``%`` is rejected for parity with the other
    # parameterized direct-query escapers (the connector treats it as a placeholder).
    if "%" in v:
        raise QueryError(f'The Snowflake identifier "{v}" is not permitted as it contains the "%" character')
    return '"' + v.replace('"', '""') + '"'


def _quote_postgres_wire_identifier(v: str, extra_reserved_keywords: set[str] | None) -> str:
    # Reject ``%`` for parity with the HogQL and ClickHouse escape paths. psycopg
    # interprets ``%`` as the start of a parameter placeholder when scanning SQL
    # passed to ``cursor.execute(sql, params)``, so a literal ``%`` slipping through
    # as an identifier name would either confuse parameter binding or get consumed
    # as a format specifier.
    if "%" in v:
        raise QueryError(f'The Postgres identifier "{v}" is not permitted as it contains the "%" character')

    if POSTGRES_SIMPLE_IDENTIFIER_REGEX.match(v):
        upper = v.upper()
        if upper not in POSTGRES_RESERVED_KEYWORDS and (
            extra_reserved_keywords is None or upper not in extra_reserved_keywords
        ):
            return v

    return '"' + v.replace('"', '""') + '"'


# Copied from clickhouse_driver.util.escape, adapted from single quotes to backquotes.
def escape_clickhouse_identifier(identifier: str) -> str:
    if "%" in identifier:
        raise QueryError(f'The HogQL identifier "{identifier}" is not permitted as it contains the "%" character')
    return quote_clickhouse_identifier(identifier)


def quote_clickhouse_identifier(identifier: str) -> str:
    """Quote an identifier without validating whether it is safe to interpolate into SQL."""
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", identifier):
        return identifier
    return "`{}`".format("".join(backquote_escape_chars_map.get(c, c) for c in identifier))


def escape_hogql_string(
    name: bool | float | int | str | list | tuple | date | datetime | UUID | UUIDT | None,
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
