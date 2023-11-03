import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def truncate_events(clickhouse_client):
    """Fixture to automatically truncate sharded_events after a test.

    This is useful if during the test setup we insert a lot of events we wish to clean-up.
    """
    yield
    await clickhouse_client.execute_query("TRUNCATE TABLE `sharded_events`")
