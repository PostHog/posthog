import pytest

from posthog.conftest import create_clickhouse_tables
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

    # Re-create the tables depending on Kafka tables.
    create_clickhouse_tables(0)

    yield

    # Drop the tables, so some other tests don't fail.
    kafka_tables = sync_execute(
        f"""
        SELECT name
        FROM system.tables
        WHERE database = '{CLICKHOUSE_DATABASE}' AND name LIKE 'kafka_%'
        """,
    )
    kafka_truncate_queries = [f"DROP TABLE {table[0]} ON CLUSTER '{CLICKHOUSE_CLUSTER}'" for table in kafka_tables]
    run_clickhouse_statement_in_parallel(kafka_truncate_queries)
