"""The wall-clock budget one delivery's consumers share."""

import time

from django.conf import settings

DEFAULT_DELIVERY_BUDGET_SECONDS = 8.0


def delivery_budget_seconds() -> float:
    """Seconds one delivery may spend in consumers, read per delivery so it can be tuned live."""
    return float(getattr(settings, "INGRESS_DELIVERY_BUDGET_SECONDS", DEFAULT_DELIVERY_BUDGET_SECONDS))


class DeliveryBudget:
    """A deadline for one delivery.

    Monotonic rather than wall clock, so an NTP step mid-delivery cannot make the budget
    look spent (or endless).
    """

    def __init__(self, seconds: float) -> None:
        self._deadline = time.monotonic() + seconds

    def is_spent(self) -> bool:
        return time.monotonic() >= self._deadline
