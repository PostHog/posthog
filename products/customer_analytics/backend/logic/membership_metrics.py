from collections.abc import Iterator
from contextlib import contextmanager
from time import monotonic
from typing import Literal

from prometheus_client import Histogram

MembershipJob = Literal["discovery", "deletion"]
BATCH_DURATION_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)
SCAN_DURATION_BUCKETS = (1, 10, 30, 60, 300, 600, 1800, 3600, 10800, 21600, 43200, 86400, 172800, 604800)
STEP_SECONDS = Histogram(
    "customer_analytics_membership_step_seconds",
    "Membership job step duration",
    ["job", "step", "outcome"],
    buckets=BATCH_DURATION_BUCKETS,
)


class MembershipTimings:
    def __init__(self, *, job: MembershipJob) -> None:
        self.job = job
        self.seconds: dict[str, float] = {}
        self.failed_step: str | None = None

    @contextmanager
    def measure(self, step: str) -> Iterator[None]:
        started = monotonic()
        outcome = "success"
        try:
            yield
        except BaseException:
            outcome = "failure"
            if self.failed_step is None:
                self.failed_step = step
            raise
        finally:
            elapsed = monotonic() - started
            self.seconds[step] = self.seconds.get(step, 0) + elapsed
            STEP_SECONDS.labels(job=self.job, step=step, outcome=outcome).observe(elapsed)
