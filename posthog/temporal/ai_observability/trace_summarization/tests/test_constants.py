from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.errors import CHQueryErrorCannotScheduleTask, CHQueryErrorTooManySimultaneousQueries
from posthog.exceptions import ClickHouseAtCapacity
from posthog.temporal.ai_observability.trace_summarization.constants import (
    CLICKHOUSE_CAPACITY_ERROR_TYPES,
    SAMPLE_RETRY_POLICY,
)


def test_capacity_error_type_names_match_real_exception_classes():
    # Temporal matches non_retryable_error_types by exception class name (a string), so a
    # rename of any capacity exception would silently make these errors retryable again and
    # re-fire sampling queries into a saturated offline cluster. Pin the names to the classes.
    expected = {
        ClickHouseAtCapacity.__name__,
        CHQueryErrorTooManySimultaneousQueries.__name__,
        CHQueryErrorCannotScheduleTask.__name__,
        ConcurrencyLimitExceeded.__name__,
    }
    assert set(CLICKHOUSE_CAPACITY_ERROR_TYPES) == expected


def test_sample_retry_policy_does_not_retry_capacity_errors():
    for name in CLICKHOUSE_CAPACITY_ERROR_TYPES:
        assert name in (SAMPLE_RETRY_POLICY.non_retryable_error_types or [])
