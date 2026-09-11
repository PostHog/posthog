from datetime import date

from posthog.dataclasses import frozen

BILLING_USAGE_RECORDS_ROLLUP_DELAY_DAYS = 28


@frozen
class BillingUsageRecordsRollupInput:
    day: str

    def __post_init__(self) -> None:
        date.fromisoformat(self.day)


@frozen
class BillingUsageRecordsRollupWorkflowInput:
    last_completed_day: str | None = None

    def __post_init__(self) -> None:
        if self.last_completed_day is not None:
            date.fromisoformat(self.last_completed_day)
