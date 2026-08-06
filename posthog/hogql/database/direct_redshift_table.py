from posthog.hogql.database.direct_postgres_table import DirectPostgresTable


class DirectRedshiftTable(DirectPostgresTable):
    """A table queried live against Amazon Redshift.

    Redshift is a fork of Postgres and shares its table-reference syntax
    (``"schema"."table"``, optionally catalog-qualified, double-quoted identifiers), so this
    reuses ``DirectPostgresTable``'s fields and ``to_printed_postgres`` rendering verbatim.
    Subclassing (rather than aliasing) keeps the ``isinstance(table, DirectPostgresTable)``
    table-printing hooks in the Postgres/Redshift printers working while leaving room for the
    dialects to diverge later. The DuckLake ``engine == "duckdb"`` catalog branch inherited
    from the parent never triggers for a Redshift connection.
    """
