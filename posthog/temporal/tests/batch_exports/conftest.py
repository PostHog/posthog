import pytest
import pytest_asyncio


@pytest.fixture
def interval(request) -> str:
    """A parametrizable fixture to configure a batch export interval.

    By decorating a test function with @pytest.mark.parametrize("interval", ..., indirect=True)
    it's possible to set the interval that will be used to create a BatchExport.
    Possible values are "hour", "day", or "every {value} {unit}".
    As interval must be defined for every BatchExport, so we default to "hour" to
    support tests that do not parametrize this.
    """
    try:
        return request.param
    except AttributeError:
        return "hour"


@pytest.fixture
def exclude_events(request) -> list[str] | None:
    """A parametrizable fixture to configure event names to exclude from a BatchExport.

    By decorating a test function with @pytest.mark.parametrize("exclude_events", ..., indirect=True)
    it's possible to set the exclude_events that will be used to create a BatchExport.
    Any list of event names can be used, or None (the default).
    """
    try:
        return request.param
    except AttributeError:
        return None


@pytest_asyncio.fixture(autouse=True)
async def truncate_events(clickhouse_client):
    """Fixture to automatically truncate sharded_events after a test.

    This is useful if during the test setup we insert a lot of events we wish to clean-up.
    """
    yield
    await clickhouse_client.execute_query("TRUNCATE TABLE `sharded_events`")
