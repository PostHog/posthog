import psycopg2
from psycopg2 import sql


from posthog.warehouse.models.ssh_tunnel import SSHTunnel
from posthog.warehouse.types import IncrementalFieldType


def filter_postgres_incremental_fields(columns: list[tuple[str, str]]) -> list[tuple[str, IncrementalFieldType]]:
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, type in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date))
        elif type == "integer" or type == "smallint" or type == "bigint":
            results.append((column_name, IncrementalFieldType.Integer))

    return results


def get_postgres_row_count(
    host: str, port: str, database: str, user: str, password: str, schema: str, ssh_tunnel: SSHTunnel
) -> dict[str, int]:
    def get_row_count(postgres_host: str, postgres_port: int):
        connection = psycopg2.connect(
            host=postgres_host,
            port=postgres_port,
            dbname=database,
            user=user,
            password=password,
            sslmode="prefer",
            connect_timeout=5,
            sslrootcert="/tmp/no.txt",
            sslcert="/tmp/no.txt",
            sslkey="/tmp/no.txt",
        )

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT tablename as table_name FROM pg_tables WHERE schemaname = %(schema)s
                    UNION ALL
                    SELECT matviewname as table_name FROM pg_matviews WHERE schemaname = %(schema)s
                    """,
                    {"schema": schema},
                )
                tables = cursor.fetchall()

                if not tables:
                    return {}

                counts = [
                    sql.SQL("SELECT {table_name} AS table_name, COUNT(*) AS row_count FROM {schema}.{table}").format(
                        table_name=sql.Literal(table[0]), schema=sql.Identifier(schema), table=sql.Identifier(table[0])
                    )
                    for table in tables
                ]

                union_counts = sql.SQL(" UNION ALL ").join(counts)
                cursor.execute(union_counts)
                row_count_result = cursor.fetchall()
                row_counts = {row[0]: row[1] for row in row_count_result}
            return row_counts
        finally:
            connection.close()

    if ssh_tunnel.enabled:
        with ssh_tunnel.get_tunnel(host, int(port)) as tunnel:
            if tunnel is None:
                raise Exception("Can't open tunnel to SSH server")

            return get_row_count(tunnel.local_bind_host, tunnel.local_bind_port)

    return get_row_count(host, int(port))


def filter_mysql_incremental_fields(columns: list[tuple[str, str]]) -> list[tuple[str, IncrementalFieldType]]:
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, type in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date))
        elif type == "datetime":
            results.append((column_name, IncrementalFieldType.DateTime))
        elif type == "tinyint" or type == "smallint" or type == "mediumint" or type == "int" or type == "bigint":
            results.append((column_name, IncrementalFieldType.Integer))

    return results


def filter_mssql_incremental_fields(columns: list[tuple[str, str]]) -> list[tuple[str, IncrementalFieldType]]:
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, type in columns:
        type = type.lower()
        if type == "date":
            results.append((column_name, IncrementalFieldType.Date))
        elif type == "datetime" or type == "datetime2" or type == "smalldatetime":
            results.append((column_name, IncrementalFieldType.DateTime))
        elif type == "tinyint" or type == "smallint" or type == "int" or type == "bigint":
            results.append((column_name, IncrementalFieldType.Integer))

    return results
