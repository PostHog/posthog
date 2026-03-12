from posthog.hogql.database.direct_postgres_table import DirectPostgresTable


class DirectDuckLakeTable(DirectPostgresTable):
    def to_printed_clickhouse(self, context) -> str:
        return super().to_printed_clickhouse(context)
