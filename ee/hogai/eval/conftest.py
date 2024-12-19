import pytest

from posthog.test.base import run_clickhouse_statement_in_parallel


@pytest.fixture(scope="module", autouse=True)
def setup_kafka_tables(django_db_setup):
    from posthog.clickhouse.client import sync_execute
    from posthog.clickhouse.schema import (
        CREATE_KAFKA_TABLE_QUERIES,
        build_query,
    )
    from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

    kafka_queries = list(map(build_query, CREATE_KAFKA_TABLE_QUERIES))
    run_clickhouse_statement_in_parallel(kafka_queries)

    yield

    kafka_tables = sync_execute(
        f"""
        SELECT name
        FROM system.tables
        WHERE database = '{CLICKHOUSE_DATABASE}' AND name LIKE 'kafka_%'
        """,
    )
    kafka_truncate_queries = [f"DROP TABLE {table[0]} ON CLUSTER '{CLICKHOUSE_CLUSTER}'" for table in kafka_tables]
    run_clickhouse_statement_in_parallel(kafka_truncate_queries)
