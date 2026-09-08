import sqlparse

from posthog.hogql.errors import ExposedHogQLError


def ensure_single_direct_statement(sql: str) -> str:
    """Reject multi-statement raw SQL.

    Raw queries run without bound parameters, so psycopg uses the simple query
    protocol, which runs every ``;``-separated statement in one round trip.
    Restricting each request to one operation keeps authorization, timeouts, and
    response accounting aligned to the statement the caller submitted. The same
    guard protects direct MySQL queries (PyMySQL additionally disables the
    MULTI_STATEMENTS client flag by default).
    """
    statements = [statement for statement in sqlparse.split(sql) if statement.strip(" \t\r\n;")]
    if len(statements) > 1:
        raise ExposedHogQLError("Raw queries must contain a single statement.")
    return sql
