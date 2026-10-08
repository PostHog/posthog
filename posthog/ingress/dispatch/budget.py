"""The wall-clock budget one delivery's consumers share."""

import math
import time

from django.conf import settings

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_DELIVERY_BUDGET_SECONDS = 8.0


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

    def is_spent(self) -> bool:
        return time.monotonic() >= self._deadline
