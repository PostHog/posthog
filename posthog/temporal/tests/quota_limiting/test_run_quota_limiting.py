import pytest
from unittest.mock import patch

from clickhouse_driver.errors import ServerException, SocketTimeoutError
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.errors import wrap_clickhouse_query_error
from posthog.temporal.quota_limiting.run_quota_limiting import (
    RunQuotaLimitingAllOrgsInputs,
    run_quota_limiting_all_orgs,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, expect_retry",
    [
        # A shard host that refuses every connection, and a busy cluster: the next attempt can land
        # on a healthy replica, so the run must not end here.
        (wrap_clickhouse_query_error(ServerException("All connection tries failed.", code=279)), True),
        (wrap_clickhouse_query_error(ServerException("Too many simultaneous queries.", code=202)), True),
        (SocketTimeoutError("Read timed out."), True),
        # A bug in the run repeats on every attempt, so retrying only adds cluster load.
        (ValueError("bad usage row"), False),
    ],
)
async def test_only_transient_clickhouse_failures_are_retried(error: Exception, expect_retry: bool):
    with patch("ee.billing.quota_limiting.update_all_orgs_billing_quotas", side_effect=error):
        with pytest.raises(ApplicationError) as ctx:
            await ActivityEnvironment().run(run_quota_limiting_all_orgs, RunQuotaLimitingAllOrgsInputs())

    assert ctx.value.non_retryable is not expect_retry
