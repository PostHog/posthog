from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.common.finops_usage_meter import FinopsUsageMeter, FinopsUsageMeterInput

WIRE_CONTRACT_FIELDS = frozenset(
    {
        "timestamp",
        "product",
        "team_id",
        "org_id",
        "feature",
        "environment",
        "billable_unit",
        "quantity",
        "system",
        "workload",
        "resource_id",
        "duration_ms",
        "service_name",
        "count",
    }
)


class TestFinopsUsageMeter:
    def test_disabled_meter_is_noop(self) -> None:
        meter = FinopsUsageMeter(enabled=False)
        meter.queue(FinopsUsageMeterInput(product="batch_exports", billable_unit="actions", quantity=1))
        with patch("posthog.temporal.common.finops_usage_meter._get_producer") as mock_get:
            meter.flush()
            mock_get.assert_not_called()

    def test_flush_produces_correct_wire_contract(self) -> None:
        meter = FinopsUsageMeter(enabled=True)
        meter.queue(
            FinopsUsageMeterInput(
                product="session_replay",
                billable_unit="actions",
                quantity=1,
                team_id=42,
                system="temporal",
                workload="rasterize-recording",
                resource_id="session-replay-task-queue",
                duration_ms=150.5,
            )
        )

        mock_producer = MagicMock()
        with (
            patch("posthog.temporal.common.finops_usage_meter._get_producer", return_value=mock_producer),
            patch("posthog.temporal.common.finops_usage_meter._resolve_environment", return_value="prod-us"),
            patch("posthog.temporal.common.finops_usage_meter._resolve_service_name", return_value="temporal-worker"),
        ):
            meter.flush()

        mock_producer.produce.assert_called_once()
        produced_data = mock_producer.produce.call_args.kwargs["data"]
        assert set(produced_data.keys()) == WIRE_CONTRACT_FIELDS
        assert produced_data["product"] == "session_replay"
        assert produced_data["team_id"] == 42
        assert produced_data["billable_unit"] == "actions"
        assert produced_data["quantity"] == 1
        assert produced_data["system"] == "temporal"
        assert produced_data["workload"] == "rasterize-recording"
        assert produced_data["duration_ms"] == 150.5
        assert produced_data["environment"] == "prod-us"
        assert produced_data["service_name"] == "temporal-worker"
        assert produced_data["count"] == 1

    def test_accumulates_quantity_duration_count_on_shared_key(self) -> None:
        meter = FinopsUsageMeter(enabled=True)
        meter.queue(
            FinopsUsageMeterInput(
                product="batch_exports",
                billable_unit="actions",
                system="temporal",
                workload="s3-export",
                quantity=1,
                duration_ms=100,
                count=1,
            )
        )
        meter.queue(
            FinopsUsageMeterInput(
                product="batch_exports",
                billable_unit="actions",
                system="temporal",
                workload="s3-export",
                quantity=1,
                duration_ms=200,
                count=1,
            )
        )
        meter.queue(
            FinopsUsageMeterInput(
                product="batch_exports",
                billable_unit="actions",
                system="temporal",
                workload="s3-export",
                quantity=1,
                duration_ms=50,
                count=1,
            )
        )

        mock_producer = MagicMock()
        with (
            patch("posthog.temporal.common.finops_usage_meter._get_producer", return_value=mock_producer),
            patch("posthog.temporal.common.finops_usage_meter._resolve_environment", return_value="dev"),
            patch("posthog.temporal.common.finops_usage_meter._resolve_service_name", return_value=""),
        ):
            meter.flush()

        mock_producer.produce.assert_called_once()
        data = mock_producer.produce.call_args.kwargs["data"]
        assert data["quantity"] == 3
        assert data["duration_ms"] == 350
        assert data["count"] == 3

    def test_distinct_dimensions_kept_separate(self) -> None:
        meter = FinopsUsageMeter(enabled=True)
        meter.queue(FinopsUsageMeterInput(product="batch_exports", billable_unit="actions", quantity=1))
        meter.queue(FinopsUsageMeterInput(product="session_replay", billable_unit="actions", quantity=1))

        mock_producer = MagicMock()
        with (
            patch("posthog.temporal.common.finops_usage_meter._get_producer", return_value=mock_producer),
            patch("posthog.temporal.common.finops_usage_meter._resolve_environment", return_value="dev"),
            patch("posthog.temporal.common.finops_usage_meter._resolve_service_name", return_value=""),
        ):
            meter.flush()

        assert mock_producer.produce.call_count == 2
        products = {call.kwargs["data"]["product"] for call in mock_producer.produce.call_args_list}
        assert products == {"batch_exports", "session_replay"}

    def test_buffer_cleared_after_flush(self) -> None:
        meter = FinopsUsageMeter(enabled=True)
        meter.queue(FinopsUsageMeterInput(product="logs", billable_unit="actions", quantity=1))

        mock_producer = MagicMock()
        with (
            patch("posthog.temporal.common.finops_usage_meter._get_producer", return_value=mock_producer),
            patch("posthog.temporal.common.finops_usage_meter._resolve_environment", return_value="dev"),
            patch("posthog.temporal.common.finops_usage_meter._resolve_service_name", return_value=""),
        ):
            meter.flush()
            mock_producer.reset_mock()
            meter.flush()

        mock_producer.produce.assert_not_called()

    def test_flush_error_does_not_propagate(self) -> None:
        meter = FinopsUsageMeter(enabled=True)
        meter.queue(FinopsUsageMeterInput(product="tasks", billable_unit="actions", quantity=1))

        with patch(
            "posthog.temporal.common.finops_usage_meter._get_producer",
            side_effect=RuntimeError("kafka down"),
        ):
            meter.flush()

    @parameterized.expand(
        [
            ("US", "prod-us"),
            ("EU", "prod-eu"),
            ("us", "prod-us"),
            ("eu", "prod-eu"),
            ("DEV", "dev"),
            ("", "dev"),
            (None, "dev"),
        ]
    )
    def test_environment_resolution(self, cloud_deployment: str | None, expected: str) -> None:
        from posthog.temporal.common.finops_usage_meter import _resolve_environment

        with patch("posthog.settings.base_variables.CLOUD_DEPLOYMENT", cloud_deployment):
            assert _resolve_environment() == expected

    def test_defaults_for_optional_fields(self) -> None:
        meter = FinopsUsageMeter(enabled=True)
        meter.queue(FinopsUsageMeterInput(product="shared", billable_unit="actions", quantity=1))

        mock_producer = MagicMock()
        with (
            patch("posthog.temporal.common.finops_usage_meter._get_producer", return_value=mock_producer),
            patch("posthog.temporal.common.finops_usage_meter._resolve_environment", return_value="dev"),
            patch("posthog.temporal.common.finops_usage_meter._resolve_service_name", return_value=""),
        ):
            meter.flush()

        data = mock_producer.produce.call_args.kwargs["data"]
        assert data["team_id"] == 0
        assert data["org_id"] == ""
        assert data["feature"] == ""
        assert data["system"] == ""
        assert data["workload"] == ""
        assert data["resource_id"] == ""
        assert data["duration_ms"] == 0.0
