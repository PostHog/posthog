import pytest
import pytest_asyncio
from django.conf import settings

from posthog.temporal.workflows.clickhouse import ClickHouseClient


@pytest.fixture
def ch_client():
    """Fixture to provide a ClickHouseClient."""
    client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )
    yield client


@pytest_asyncio.fixture
async def truncate_events(ch_client):
    """Fixture to truncate sharded_events after a test.

    This is useful if during the test setup we insert a lot of events we wish to clean-up.
    """
    yield
    await ch_client.execute_query("TRUNCATE TABLE `sharded_events`")
