import inspect

import pytest
from unittest.mock import MagicMock, patch

from prometheus_client import CollectorRegistry

from posthog.temporal.scheduler.metrics import SchedulerMetrics, record_scheduler_metrics_safely


def test_scheduler_metrics_expose_only_low_cardinality_dimensions() -> None:
    registry = CollectorRegistry()
    metrics = SchedulerMetrics(registry=registry)

    metrics.observe_payload("subscriptions", "eu", "discovery", 1_024)
    metrics.record_admission("subscriptions", "eu", "reserved", 3)
    metrics.record_claim_transition("subscriptions", "eu", "confirmed")
    metrics.set_permits_in_flight("subscriptions", "eu", 7)
    metrics.set_backlog("subscriptions", "eu", due_items_lower_bound=300, oldest_age_seconds=90)

    assert (
        registry.get_sample_value(
            "posthog_temporal_scheduler_payload_bytes_count",
            {"scheduler": "subscriptions", "region": "eu", "payload_kind": "discovery"},
        )
        == 1
    )
    assert (
        registry.get_sample_value(
            "posthog_temporal_scheduler_admission_total",
            {"scheduler": "subscriptions", "region": "eu", "outcome": "reserved"},
        )
        == 3
    )
    assert (
        registry.get_sample_value(
            "posthog_temporal_scheduler_claim_transition_total",
            {"scheduler": "subscriptions", "region": "eu", "transition": "confirmed"},
        )
        == 1
    )
    assert (
        registry.get_sample_value(
            "posthog_temporal_scheduler_permits_in_flight",
            {"scheduler": "subscriptions", "region": "eu"},
        )
        == 7
    )
    assert (
        registry.get_sample_value(
            "posthog_temporal_scheduler_backlog_items_lower_bound",
            {"scheduler": "subscriptions", "region": "eu"},
        )
        == 300
    )
    assert (
        registry.get_sample_value(
            "posthog_temporal_scheduler_backlog_oldest_age_seconds",
            {"scheduler": "subscriptions", "region": "eu"},
        )
        == 90
    )

    for method_name in [
        "observe_payload",
        "record_admission",
        "record_claim_transition",
        "set_permits_in_flight",
        "set_backlog",
    ]:
        parameters = inspect.signature(getattr(metrics, method_name)).parameters
        assert "tenant_key" not in parameters
        assert "occurrence_key" not in parameters

    assert metrics._permits_in_flight._multiprocess_mode == "mostrecent"
    assert metrics._backlog_items_lower_bound._multiprocess_mode == "mostrecent"
    assert metrics._backlog_oldest_age_seconds._multiprocess_mode == "mostrecent"


@pytest.mark.parametrize(
    "method,args",
    [
        ("observe_payload", (" ", "eu", "discovery", 1)),
        ("record_admission", ("subscriptions", " ", "reserved", 1)),
        ("observe_payload", ("subscriptions", "eu", "unknown", 1)),
        ("record_admission", ("subscriptions", "eu", "unknown", 1)),
        ("record_claim_transition", ("subscriptions", "eu", "unknown")),
        ("set_permits_in_flight", ("subscriptions", "eu", -1)),
        ("set_backlog", ("subscriptions", "eu", -1, 0)),
        ("set_backlog", ("subscriptions", "eu", 0, -1)),
    ],
)
def test_scheduler_metrics_reject_unbounded_or_invalid_values(method: str, args: tuple[object, ...]) -> None:
    metrics = SchedulerMetrics(registry=CollectorRegistry())

    with pytest.raises(ValueError):
        getattr(metrics, method)(*args)


@patch("posthog.temporal.scheduler.metrics.LOGGER.exception")
def test_metric_backend_failure_is_best_effort(log_exception: MagicMock) -> None:
    def fail() -> None:
        raise RuntimeError("registry unavailable")

    record_scheduler_metrics_safely(fail)

    log_exception.assert_called_once_with("temporal_scheduler.metric_recording_failed")
