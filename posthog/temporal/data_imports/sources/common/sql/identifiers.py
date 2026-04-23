"""Identifier quoting and allowlist validation for SQL-based sources.

The single place where *unparameterized* strings (schema / table / column
names) are allowed to reach a SQL query. Every SQL source must go through
an `IdentifierQuoter` implementation so the allowlist check is uniform and
cannot be bypassed by subclasses. The allowlist is strict (alphanumeric,
`_`, `-`, `.`, `$`, `@`) — anything else raises `InvalidIdentifierError`.

The check matches today's `mysql._sanitize_identifier` (the only driver that
already validated identifiers) and is applied to every driver so MSSQL,
Snowflake, BigQuery, Redshift, and ClickHouse inherit the same guarantees.
"""

from __future__ import annotations

import re
from typing import Protocol


class InvalidIdentifierError(ValueError):
    """Raised when an identifier fails the allowlist check.

    Subclasses `ValueError` so existing callers that catch `ValueError`
    (`mysql._sanitize_identifier` raised plain `ValueError`) keep working.
    """


_ALLOWED_EXTRA_CHARS = set("._-$@")
_ALL_DIGITS = re.compile(r"^\d+$")


def _validate_identifier(identifier: str) -> None:
    """Allowlist check shared by every concrete quoter.

    Accepts: alphanumeric plus `.`, `_`, `-`, `$`, `@`. An identifier that
    is nothing but digits is also allowed (matches today's MySQL behavior
    where `"851"` is quoted verbatim). Anything else — whitespace, a
    semicolon, a quote character, a NUL byte — raises.
    """
    if not identifier:
        raise InvalidIdentifierError("Identifier may not be empty")

    if _ALL_DIGITS.match(identifier):
        return

    for ch in identifier:
        if ch.isalnum() or ch in _ALLOWED_EXTRA_CHARS:
            continue
        raise InvalidIdentifierError(f"Invalid SQL identifier: {identifier!r}")


class IdentifierQuoter(Protocol):
    """Driver-specific quoting of a validated identifier.

    Subclasses implement the quoting style that matches their dialect
    (backticks for MySQL, double-quotes for Postgres/ANSI, square brackets
    for T-SQL). `quote` MUST call `_validate_identifier` on the input before
    any quoting so a subclass cannot skip the allowlist check.
    """

    def quote(self, identifier: str) -> str: ...

    def quote_qualified(self, *parts: str) -> str:
        """Quote each part and join with '.' for a fully-qualified reference."""


class _BaseQuoter:
    """Shared implementation detail for the two concrete quoters below.

    Deliberately not exported — external callers use the `IdentifierQuoter`
    protocol, which is all the `SelectQueryBuilder` needs.
    """

    _open: str
    _close: str

    def quote(self, identifier: str) -> str:
        _validate_identifier(identifier)
        return f"{self._open}{identifier}{self._close}"

    def quote_qualified(self, *parts: str) -> str:
        if not parts:
            raise InvalidIdentifierError("quote_qualified requires at least one part")
        return ".".join(self.quote(p) for p in parts)


class BacktickIdentifierQuoter(_BaseQuoter):
    """MySQL / MariaDB / ClickHouse quoting with backticks."""

    _open = "`"
    _close = "`"


class AnsiIdentifierQuoter(_BaseQuoter):
    """ANSI SQL quoting with double-quotes (Postgres, Redshift, Snowflake)."""

    _open = '"'
    _close = '"'
