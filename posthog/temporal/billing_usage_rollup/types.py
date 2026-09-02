from datetime import date

from posthog.dataclasses import frozen


@frozen
class BillingUsageRecordsRollupInput:
    day: str | None = None

    def __post_init__(self) -> None:
        if self.day is not None:
            date.fromisoformat(self.day)
