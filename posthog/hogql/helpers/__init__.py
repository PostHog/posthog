import re
from typing import NamedTuple


class PostgresDialectInfo(NamedTuple):
    uses_postgres: bool
    source_id: str | None = None


def uses_postgres_dialect(query: str | None) -> bool:
    """Detect whether a HogQL query is marked to use the Postgres dialect."""

    if not query:
        return False

    stripped_query = query.strip()
    return (
        stripped_query.startswith("--pg")
        or stripped_query.startswith("-- pg")
        or stripped_query.endswith("--pg")
        or stripped_query.endswith("-- pg")
    )


def parse_postgres_directive(query: str | None) -> PostgresDialectInfo:
    """Parse Postgres dialect directive from a HogQL query.

    Supports formats:
    - --pg or -- pg: Regular Postgres dialect (executes against Django DB)
    - --pg:UUID: Direct query to external Postgres source identified by UUID

    Returns a PostgresDialectInfo with:
    - uses_postgres: True if any Postgres dialect marker is present
    - source_id: UUID of the external source if specified (indicates direct query)
    """
    if not query:
        return PostgresDialectInfo(uses_postgres=False)

    stripped_query = query.strip()

    # Check for --pg:UUID format (direct query to external source)
    uuid_pattern = r"--pg:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    match = re.search(uuid_pattern, stripped_query)
    if match:
        return PostgresDialectInfo(uses_postgres=True, source_id=match.group(1))

    # Check for regular --pg format
    if uses_postgres_dialect(query):
        return PostgresDialectInfo(uses_postgres=True)

    return PostgresDialectInfo(uses_postgres=False)
