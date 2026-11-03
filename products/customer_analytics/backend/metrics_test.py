import pytest
from unittest.mock import MagicMock, patch

from products.customer_analytics.backend.metrics import (
    record_account_property_sync_phase_duration,
    record_membership_operation,
)


@pytest.mark.parametrize("lag_seconds", [None, 0, 12.5])
def test_membership_lag_records_only_measured_values(lag_seconds: float | None) -> None:
    client = MagicMock()
    with patch("products.customer_analytics.backend.metrics.posthoganalytics.default_client", client):
        record_membership_operation("backfill", "catching_up", lag_seconds=lag_seconds)
    if lag_seconds is None:
        client.metrics.histogram.assert_not_called()
    else:
        client.metrics.histogram.assert_called_once_with("customer_analytics.membership.lag", lag_seconds, unit="s")


def test_account_property_sync_phase_duration_records_posthog_metric() -> None:
    client = MagicMock()

    with patch("products.customer_analytics.backend.metrics.posthoganalytics.default_client", client):
        record_account_property_sync_phase_duration(
            phase="apply_values",
            segment="tracked",
            duration_seconds=1.25,
        )

    client.metrics.histogram.assert_called_once_with(
        "customer_analytics_account_property_sync_phase_duration_seconds",
        1.25,
        unit="s",
        attributes={"phase": "apply_values", "segment": "tracked"},
    )


def test_account_property_sync_phase_duration_ignores_metric_failures() -> None:
    client = MagicMock()
    client.metrics.histogram.side_effect = RuntimeError()

    with patch("products.customer_analytics.backend.metrics.posthoganalytics.default_client", client):
        record_account_property_sync_phase_duration(
            phase="apply_values",
            segment="tracked",
            duration_seconds=1.25,
        )
