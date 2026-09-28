import pytest
from unittest.mock import AsyncMock, patch

from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.exceptions import ClickHouseAtCapacity
from posthog.temporal.experiments.activities import (
    CLICKHOUSE_AT_CAPACITY_RETRY_DELAY_MAX,
    CLICKHOUSE_AT_CAPACITY_RETRY_DELAY_MIN,
    calculate_experiment_regular_metric,
    calculate_experiment_saved_metric,
)

ACTIVITIES = [
    (calculate_experiment_regular_metric, "_calculate_experiment_regular_metric_sync"),
    (calculate_experiment_saved_metric, "_calculate_experiment_saved_metric_sync"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("activity_fn,sync_name", ACTIVITIES)
async def test_clickhouse_at_capacity_retries_after_backoff(activity_fn, sync_name):
    with patch(
        f"posthog.temporal.experiments.activities.{sync_name}",
        new=AsyncMock(side_effect=ClickHouseAtCapacity()),
    ):
        with pytest.raises(ApplicationError) as exc_info:
            await ActivityEnvironment().run(activity_fn, 1, "metric-uuid", "fingerprint")

    error = exc_info.value
    assert error.type == "ClickHouseAtCapacity"
    assert not error.non_retryable
    assert error.next_retry_delay is not None
    assert CLICKHOUSE_AT_CAPACITY_RETRY_DELAY_MIN <= error.next_retry_delay <= CLICKHOUSE_AT_CAPACITY_RETRY_DELAY_MAX


@pytest.mark.asyncio
@pytest.mark.parametrize("activity_fn,sync_name", ACTIVITIES)
async def test_other_failures_keep_the_default_retry(activity_fn, sync_name):
    with patch(
        f"posthog.temporal.experiments.activities.{sync_name}",
        new=AsyncMock(side_effect=ValueError("boom")),
    ):
        with pytest.raises(ValueError):
            await ActivityEnvironment().run(activity_fn, 1, "metric-uuid", "fingerprint")
