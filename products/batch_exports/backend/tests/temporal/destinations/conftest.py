import pytest

from products.batch_exports.backend.tests.temporal.utils import (
    create_clickhouse_tables_and_views,
    truncate_events,
    truncate_persons,
    truncate_sessions,
)


@pytest.fixture(scope="module", autouse=True)
async def clickhouse_db_setup(clickhouse_client, django_db_setup):
    await create_clickhouse_tables_and_views(clickhouse_client)


@pytest.fixture(autouse=True)
async def truncate(clickhouse_client):
    """Fixture to automatically truncate data after a test.

    This is useful if during the test setup we insert a lot of data we wish to clean-up.
    """
    yield
    await truncate_events(clickhouse_client)
    await truncate_persons(clickhouse_client)
    await truncate_sessions(clickhouse_client)
