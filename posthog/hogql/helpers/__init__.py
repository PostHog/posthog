import re
from typing import NamedTuple


class PostgresDialectInfo(NamedTuple):
    uses_postgres: bool
    source_id: str | None = None
    is_direct: bool = False


def uses_postgres_dialect(query: str | None) -> bool:
    """Detect whether a HogQL query is marked to use the Postgres dialect."""

    if not query:
        return False

    stripped_query = query.strip()
    return bool(
        re.search(r"--\s*pg\b", stripped_query, re.IGNORECASE)
        or re.search(r"--\s*direct\b", stripped_query, re.IGNORECASE)
    )


def parse_postgres_directive(query: str | None) -> PostgresDialectInfo:
    """Parse Postgres dialect directive from a HogQL query.

    Supports formats:
    - --pg or -- pg: Regular Postgres dialect (executes against Django DB)
    - --pg:UUID: Direct query to external Postgres source identified by UUID
    - --direct:UUID: Direct SQL query to external Postgres source identified by UUID
    - --direct: Direct SQL query to the default Postgres connection

    Returns a PostgresDialectInfo with:
    - uses_postgres: True if any Postgres dialect marker is present
    - source_id: UUID of the external source if specified (indicates direct query)
    - is_direct: True if the directive requests skipping HogQL translation
    """
    if not query:
        return PostgresDialectInfo(uses_postgres=False)

    stripped_query = query.strip()

    direct_pattern = r"--\s*direct(?::([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}))?"
    direct_match = re.search(direct_pattern, stripped_query, flags=re.IGNORECASE)
    if direct_match:
        return PostgresDialectInfo(uses_postgres=True, source_id=direct_match.group(1), is_direct=True)

    # Check for --pg:UUID format (direct query to external source)
    uuid_pattern = r"--\s*pg:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    match = re.search(uuid_pattern, stripped_query, flags=re.IGNORECASE)
    if match:
        return PostgresDialectInfo(uses_postgres=True, source_id=match.group(1))

    # Check for regular --pg format
    if re.search(r"--\s*pg\b", stripped_query, flags=re.IGNORECASE):
        return PostgresDialectInfo(uses_postgres=True)

    return PostgresDialectInfo(uses_postgres=False)
