import pytest
from infi.clickhouse_orm import Database

from ee.clickhouse.client import sync_execute
from posthog.settings import (
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HTTP_URL,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_USER,
    CLICKHOUSE_VERIFY,
)


@pytest.fixture(scope="package")
def django_db_setup(django_db_setup):
    database = Database(
        CLICKHOUSE_DATABASE,
        db_url=CLICKHOUSE_HTTP_URL,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        verify_ssl_cert=CLICKHOUSE_VERIFY,
    )
    try:
        database.drop_database()
    except:
        pass
    database.create_database()
    database.migrate("ee.clickhouse.migrations")
    # Make DELETE / UPDATE synchronous to avoid flaky tests
    sync_execute("SET mutations_sync = 1")

    yield

    try:
        database.drop_database()
    except:
        pass
