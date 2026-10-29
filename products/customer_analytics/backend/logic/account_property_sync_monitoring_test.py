import json
from collections.abc import Iterator
from dataclasses import asdict
from typing import Any, Literal

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.dataclasses import frozen
from posthog.ph_client import ScopedCapture

from products.customer_analytics.backend.logic.account_property_sync_monitoring import (
    capture_account_property_sync_event,
)

MODULE = "products.customer_analytics.backend.logic.account_property_sync_monitoring"

REQUIRED: dict[str, Any] = {
    "team_id": 42,
    "saved_query_id": "view-0001",
    "job_id": "job-0001",
    "segment": "tracked",
}
ALLOWED_METRIC_ATTRIBUTES = {
    "path": {"legacy", "fanout"},
    "segment": {"tracked", "ignored", "unknown"},
    "status": {"started", "completed", "failed", "cancelled"},
    "is_retry": {"true", "false", "unknown"},
    "kind": {"read", "changed", "matched", "written"},
}


@frozen
class _MetricCall:
    instrument: Literal["count", "histogram"]
    name: str
    value: float
    unit: str | None
    attributes: dict[str, str]


class TestCaptureAccountPropertySyncEvent:
    @pytest.fixture(autouse=True)
    def sinks(self) -> Iterator[None]:
        self.capture = MagicMock()
        self.client = MagicMock()
        with (
            patch(f"{MODULE}.ph_background_capture", return_value=self.capture) as background,
            patch(f"{MODULE}.posthoganalytics.default_client", self.client),
        ):
            self.background = background
            yield

    def _metric_calls(self) -> list[_MetricCall]:
        instruments: tuple[tuple[Literal["count", "histogram"], MagicMock], ...] = (
            ("count", self.client.metrics.count),
            ("histogram", self.client.metrics.histogram),
        )
        return [
            _MetricCall(
                instrument=instrument,
                name=c.args[0],
                value=c.args[1],
                unit=c.kwargs["unit"],
                attributes=c.kwargs["attributes"],
            )
            for instrument, mock in instruments
            for c in mock.call_args_list
        ]

    @parameterized.expand(
        [
            (
                "fanout_attempt_with_every_optional_field",
                {
                    "path": "fanout",
                    "scope": "attempt",
                    "status": "failed",
                    "source_id": "source-0001",
                    "duration_seconds": 12.5,
                    "attempt": 2,
                    "source_count": 3,
                    "counts": {"rows_read": 10, "changed": 4, "matched": 3, "written": 2, "source_errors": 1},
                    "error_type": "ApplicationError",
                    "workflow_id": "wf-0001",
                    "workflow_run_id": "run-0001",
                },
                {
                    "path": "fanout",
                    "scope": "attempt",
                    "status": "failed",
                    "source_id": "source-0001",
                    "duration_seconds": 12.5,
                    "attempt": 2,
                    "is_retry": True,
                    "source_count": 3,
                    "rows_read": 10,
                    "rows_changed": 4,
                    "rows_matched": 3,
                    "rows_written": 2,
                    "source_errors": 1,
                    "error_type": "ApplicationError",
                    "workflow_id": "wf-0001",
                    "workflow_run_id": "run-0001",
                },
                "US",
            ),
            (
                "legacy_segment_without_optional_fields",
                {"path": "legacy", "scope": "segment", "status": "started"},
                {"path": "legacy", "scope": "segment", "status": "started"},
                "EU",
            ),
        ]
    )
    def test_emits_personless_event_with_only_provided_fields(
        self, _name: str, kwargs: dict[str, Any], expected_properties: dict[str, Any], region: str
    ) -> None:
        with override_settings(CLOUD_DEPLOYMENT=region):
            capture_account_property_sync_event(**REQUIRED, **kwargs)

        self.capture.assert_called_once_with(
            distinct_id="warehouse_account_property_sync_team_42",
            event="warehouse_account_property_sync",
            properties={
                "$process_person_profile": False,
                "team_id": 42,
                "region": region,
                "saved_query_id": "view-0001",
                "job_id": "job-0001",
                "segment": "tracked",
                **expected_properties,
            },
        )

    def test_drops_untrusted_values_before_they_reach_any_sink(self) -> None:
        capture_account_property_sync_event(
            team_id=42,
            saved_query_id="view-0001",
            job_id="job-0001",
            segment="acme-secret-segment",
            path="fanout",
            scope="attempt",
            status="failed",
            duration_seconds=float("nan"),
            attempt=0,
            source_count=-1,
            counts={"rows_read": -5, "changed": True, "matched": 3, "customer_value": 99, "ACME@example.com": 1},
            error_type="ValueError: invalid value 'ACME@example.com' for property plan",
        )

        properties = self.capture.call_args.kwargs["properties"]
        assert properties["segment"] == "unknown"
        assert properties["error_type"] == "invalid"
        assert properties["rows_matched"] == 3
        for absent in ("duration_seconds", "attempt", "is_retry", "source_count", "rows_read", "rows_changed"):
            assert absent not in properties
        emitted = json.dumps([properties, [asdict(c) for c in self._metric_calls()]]).lower()
        for leaked in ("acme", "customer_value", "invalid value", "nan", "99"):
            assert leaked not in emitted

    @parameterized.expand(
        [
            ("path", {"path": "shadow", "scope": "attempt", "status": "completed"}),
            ("scope", {"path": "legacy", "scope": "source", "status": "completed"}),
            ("status", {"path": "legacy", "scope": "attempt", "status": "succeeded"}),
        ]
    )
    def test_rejects_values_outside_the_enums(self, _name: str, kwargs: dict[str, Any]) -> None:
        capture_account_property_sync_event(**REQUIRED, **kwargs)

        self.background.assert_not_called()
        assert self._metric_calls() == []

    @parameterized.expand(
        [
            ("background_client_unavailable", "background", "event"),
            ("event_enqueue_fails", "capture", "event"),
            ("metric_record_fails", "metrics", "metrics"),
        ]
    )
    def test_sink_failures_never_raise_and_spare_the_other_sink(
        self, _name: str, failing: str, failed_sink: str
    ) -> None:
        error = RuntimeError("token phx_fake_secret leaked")
        {
            "background": self.background,
            "capture": self.capture,
            "metrics": self.client.metrics.count,
        }[failing].side_effect = error

        with patch(f"{MODULE}.logger") as logger:
            capture_account_property_sync_event(**REQUIRED, path="legacy", scope="attempt", status="completed")

        assert (self.capture.called if failed_sink == "metrics" else self.client.metrics.count.called) is True
        logger.warning.assert_called_once()
        assert "phx_fake_secret" not in str(logger.warning.call_args)

    @parameterized.expand(
        [
            (
                "terminal_attempt",
                {
                    "path": "fanout",
                    "scope": "attempt",
                    "status": "completed",
                    "attempt": 1,
                    "duration_seconds": 3.5,
                    "source_count": 3,
                    "counts": {"rows_read": 10, "changed": 4, "matched": 3, "written": 2, "source_errors": 1},
                },
                [
                    _MetricCall(
                        instrument="count",
                        name="customer_analytics.account_property_sync.attempts",
                        value=1,
                        unit="{attempt}",
                        attributes={"path": "fanout", "segment": "tracked", "status": "completed", "is_retry": "false"},
                    ),
                    *[
                        _MetricCall(
                            instrument="count",
                            name="customer_analytics.account_property_sync.rows",
                            value=value,
                            unit="{row}",
                            attributes={"path": "fanout", "segment": "tracked", "status": "completed", "kind": kind},
                        )
                        for kind, value in (("read", 10), ("changed", 4), ("matched", 3), ("written", 2))
                    ],
                    _MetricCall(
                        instrument="count",
                        name="customer_analytics.account_property_sync.source_errors",
                        value=1,
                        unit="{source}",
                        attributes={"path": "fanout", "segment": "tracked", "status": "completed"},
                    ),
                    _MetricCall(
                        instrument="histogram",
                        name="customer_analytics.account_property_sync.attempt.duration",
                        value=3.5,
                        unit="s",
                        attributes={"path": "fanout", "segment": "tracked", "status": "completed"},
                    ),
                ],
            ),
            (
                "started_attempt_records_no_terminal_measures",
                {
                    "path": "legacy",
                    "scope": "attempt",
                    "status": "started",
                    "duration_seconds": 3.5,
                    "counts": {"rows_read": 10},
                },
                [
                    _MetricCall(
                        instrument="count",
                        name="customer_analytics.account_property_sync.attempts",
                        value=1,
                        unit="{attempt}",
                        attributes={"path": "legacy", "segment": "tracked", "status": "started", "is_retry": "unknown"},
                    ),
                ],
            ),
            (
                "terminal_segment_skips_row_counters",
                {
                    "path": "legacy",
                    "scope": "segment",
                    "status": "cancelled",
                    "attempt": 3,
                    "duration_seconds": 61.0,
                    "source_count": 2,
                    "counts": {"rows_read": 10, "source_errors": 1},
                },
                [
                    _MetricCall(
                        instrument="count",
                        name="customer_analytics.account_property_sync.segments",
                        value=1,
                        unit="{segment}",
                        attributes={"path": "legacy", "segment": "tracked", "status": "cancelled"},
                    ),
                    _MetricCall(
                        instrument="histogram",
                        name="customer_analytics.account_property_sync.segment.duration",
                        value=61.0,
                        unit="s",
                        attributes={"path": "legacy", "segment": "tracked", "status": "cancelled"},
                    ),
                    _MetricCall(
                        instrument="histogram",
                        name="customer_analytics.account_property_sync.segment.sources",
                        value=2,
                        unit="{source}",
                        attributes={"path": "legacy", "segment": "tracked", "status": "cancelled"},
                    ),
                ],
            ),
        ]
    )
    def test_records_low_cardinality_sdk_metrics(
        self, _name: str, kwargs: dict[str, Any], expected: list[_MetricCall]
    ) -> None:
        capture_account_property_sync_event(
            **REQUIRED, source_id="source-0001", workflow_id="wf-0001", workflow_run_id="run-0001", **kwargs
        )

        recorded = self._metric_calls()
        assert recorded == expected
        for call in recorded:
            for key, value in call.attributes.items():
                assert value in ALLOWED_METRIC_ATTRIBUTES[key]

    def test_skips_both_sinks_inside_workflow_code(self) -> None:
        with patch("temporalio.workflow.in_workflow", return_value=True):
            capture_account_property_sync_event(**REQUIRED, path="fanout", scope="segment", status="completed")

        self.background.assert_not_called()
        assert self._metric_calls() == []

    def test_disabled_sinks_send_nothing(self) -> None:
        client = MagicMock()
        self.background.return_value = ScopedCapture(client)

        with (
            patch("posthog.ph_client.is_cloud", return_value=False),
            patch(f"{MODULE}.posthoganalytics.default_client", None),
        ):
            capture_account_property_sync_event(**REQUIRED, path="legacy", scope="attempt", status="completed")

        assert client.mock_calls == []
