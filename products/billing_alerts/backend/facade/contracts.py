from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from products.billing_alerts.backend.models import BillingAlertEvent


@dataclass(frozen=True)
class BillingAlertDispatchResult:
    event: BillingAlertEvent
    dispatched_destinations: int
