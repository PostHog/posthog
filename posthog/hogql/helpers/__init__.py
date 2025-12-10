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
