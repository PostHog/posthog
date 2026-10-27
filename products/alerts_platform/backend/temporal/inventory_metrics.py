"""Inventory gauges for the worker health dashboard.

Pushed to the PushGateway rather than exported through Temporal's meter, so the region holds one
series per label set and no worker replica keeps an older count. The PushGateway's
`push_time_seconds` for the job shows how fresh the counts are.
"""

from collections.abc import Sequence

from prometheus_client import Gauge

from posthog.metrics import pushed_metrics_registry

from products.alerts_platform.backend.logic.inventory import SourceInventory

# The timeout applies to the connect and to the response separately, so a stalled PushGateway
# holds the push for up to 10 seconds. That stays inside the 20-second activity timeout.
PUSH_TIMEOUT_SECONDS = 5


def push_inventory(inventories: Sequence[SourceInventory]) -> None:
    with pushed_metrics_registry("alerts_platform_inventory", timeout=PUSH_TIMEOUT_SECONDS) as registry:
        configurations = Gauge(
            "alerts_platform_configurations",
            "Platform alert configurations, by source, whether they are enabled, and which stack owns them",
            ["source", "enabled", "owner"],
            registry=registry,
        )
        alerts = Gauge(
            "alerts_platform_alerts",
            "Runtime rows of enabled platform alert configurations, by state and whether they are muted",
            ["source", "state", "muted"],
            registry=registry,
        )
        for inventory in inventories:
            source = inventory.source.value
            for configuration in inventory.configurations:
                configurations.labels(
                    source=source, enabled=str(configuration.enabled).lower(), owner=configuration.owner.value
                ).set(configuration.count)
            for alert in inventory.alerts:
                alerts.labels(source=source, state=alert.state.value, muted=str(alert.muted).lower()).set(alert.count)
