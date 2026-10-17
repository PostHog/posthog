"""The wall-clock budget one delivery's consumers share."""

import math
import time

from django.conf import settings

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_DELIVERY_BUDGET_SECONDS = 8.0

BEFORE_DISPATCH = "before_dispatch"


def delivery_budget_seconds() -> float:
    """Seconds one delivery may spend in consumers, read per delivery so it can be tuned live.

    A value that is not positive and finite falls back to the default rather than being
    honored: zero or less skips every consumer, and infinity or NaN removes the backstop.
    """
    seconds = float(getattr(settings, "INGRESS_DELIVERY_BUDGET_SECONDS", DEFAULT_DELIVERY_BUDGET_SECONDS))
    if not math.isfinite(seconds) or seconds <= 0:
        logger.warning(
            "ingress_delivery_budget_invalid",
            setting="INGRESS_DELIVERY_BUDGET_SECONDS",
            configured=seconds,
            default=DEFAULT_DELIVERY_BUDGET_SECONDS,
        )
        return DEFAULT_DELIVERY_BUDGET_SECONDS
    return seconds


class DeliveryBudget:
    """A deadline for one delivery.

    Monotonic rather than wall clock, so an NTP step mid-delivery cannot make the budget
    look spent (or endless).
    """

    def __init__(self, seconds: float) -> None:
        self._deadline = time.monotonic() + seconds
        self._seconds_by_consumer: dict[str, float] = {}

    def is_spent(self) -> bool:
        return time.monotonic() >= self._deadline

    def record_run(self, consumer: str, seconds: float) -> None:
        self._seconds_by_consumer[consumer] = self._seconds_by_consumer.get(consumer, 0.0) + seconds

    @property
    def exhausted_by(self) -> str:
        """The consumer that spent the most of the budget, which is the one to fix.

        The last consumer to run is not it: a fast consumer can cross a deadline a slow one used up.
        The budget spans every delivery of the request, so that consumer can belong to an earlier
        delivery. It is `BEFORE_DISPATCH` when no consumer ran at all, because the ownership lookups
        and the forward draw from the same budget before dispatch starts.
        """
        if not self._seconds_by_consumer:
            return BEFORE_DISPATCH
        return max(self._seconds_by_consumer, key=self._seconds_by_consumer.__getitem__)

    @property
    def seconds_by_consumer(self) -> dict[str, float]:
        return dict(self._seconds_by_consumer)
