import datetime as dt

import pytest

from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse


@pytest.fixture
def generate_events(clickhouse_client, ateam):
    """Factory fixture to generate test events in ClickHouse with sensible defaults.

    Returns a coroutine function that can be awaited with custom parameters.
    Defaults: table="sharded_events", end_time=start_time+1h, inserted_at=start_time.
    """

    async def _generate(
        start_time: dt.datetime,
        end_time: dt.datetime | None = None,
        inserted_at: dt.datetime | None = None,
        count: int = 10,
        event_name: str = "test-event",
        count_outside_range: int = 0,
        count_other_team: int = 0,
    ):
        await generate_test_events_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=start_time,
            end_time=end_time or start_time + dt.timedelta(hours=1),
            count=count,
            inserted_at=inserted_at or start_time,
            table="sharded_events",
            event_name=event_name,
            count_outside_range=count_outside_range,
            count_other_team=count_other_team,
        )

    return _generate
