"""Contract types for insight alerts.

Framework-free values this product hands to its consumers. The alerting vocabulary every source
shares lives in `products.alerts_platform.backend.facade.contracts`; what stays here is what only
an insight alert means.
"""

from __future__ import annotations

from typing import Final

from posthog.cdp.internal_events import LEGACY_INSIGHT_ALERT_EVENT

from products.alerts_platform.backend.facade.contracts import DestinationType

# The internal event an insight alert's destinations fire on. Do not take it from
# `posthog.tasks.alerts.utils` instead, because that module imports this product's facade.
INSIGHT_ALERT_EVENT_IDS: Final[tuple[str, ...]] = (LEGACY_INSIGHT_ALERT_EVENT,)

# Slack only, because `alert:write` is grantable to a sandboxed agent. A connected workspace is a
# destination an admin chose, while every other transport takes a URL the caller supplies.
INSIGHT_ALERT_DESTINATION_TYPES: Final[tuple[DestinationType, ...]] = (DestinationType.SLACK,)
