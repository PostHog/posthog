from unittest.mock import MagicMock, patch

from products.customer_analytics.backend.metrics import record_account_property_sync_phase_duration


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
