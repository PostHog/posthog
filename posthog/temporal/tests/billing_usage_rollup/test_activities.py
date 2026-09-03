from datetime import date

import pytest
from unittest.mock import patch

from temporalio.testing import ActivityEnvironment

from posthog.temporal.billing_usage_rollup.activities import rollup_billing_usage_records
from posthog.temporal.billing_usage_rollup.types import BillingUsageRecordsRollupInput


@pytest.mark.asyncio
async def test_rollup_activity_uses_the_requested_day() -> None:
    with patch("posthog.temporal.billing_usage_rollup.activities.rollup_billing_usage_records_day") as rollup:
        await ActivityEnvironment().run(rollup_billing_usage_records, BillingUsageRecordsRollupInput(day="2026-05-05"))

    rollup.assert_called_once_with(date(2026, 5, 5))
