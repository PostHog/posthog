import datetime as dt

import temporalio.common

BILLING_ALERT_EVALUATE_RETRY_POLICY = temporalio.common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=10),
    maximum_interval=dt.timedelta(minutes=2),
    maximum_attempts=3,
)
