import datetime as dt

from temporalio.common import RetryPolicy

# The fork activity runs the Max LangGraph. It is the most expensive step but cannot be
# parallelized; conservative retry on transient failures.
FORK_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=5),
    maximum_interval=dt.timedelta(minutes=1),
    backoff_coefficient=2.0,
    maximum_attempts=3,
)

# Judge calls are cheap and idempotent — retry aggressively to smooth over upstream blips.
JUDGE_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=2),
    maximum_interval=dt.timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_attempts=5,
)

# emit_signal is fire-and-forget into Temporal-backed buffer; bounded retries.
EMIT_SIGNAL_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=2),
    maximum_interval=dt.timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_attempts=5,
)

DEFAULT_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=2),
    maximum_interval=dt.timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_attempts=3,
)
