from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.finops.celery_task_product_map import CeleryTaskProduct, resolve_celery_task_product
from posthog.finops.usage_meter import FinopsUsageMeter, FinopsUsageMeterInput

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
        "user_id",
    }
)


class TestFinopsUsageMeter:
    def test_disabled_meter_is_noop(self) -> None:
        meter = FinopsUsageMeter(enabled=False)
        meter.queue(FinopsUsageMeterInput(product="shared", billable_unit="events", quantity=1))
        with patch("posthog.finops.usage_meter._get_producer") as mock_get:
            meter.flush()
            mock_get.assert_not_called()

    def test_flush_produces_correct_wire_contract(self) -> None:
        meter = FinopsUsageMeter(enabled=True)
        meter.queue(
            FinopsUsageMeterInput(
                product="feature_flags",
                billable_unit="flag_requests",
                quantity=1,
                team_id=42,
                system="celery",
                workload="posthog.tasks.tasks.compute_feature_flag_metrics",
                resource_id="celery",
                duration_ms=150.5,
            )
        )

        mock_producer = MagicMock()
        with (
            patch("posthog.finops.usage_meter._get_producer", return_value=mock_producer),
            patch("posthog.finops.usage_meter._resolve_environment", return_value="prod-us"),
            patch("posthog.finops.usage_meter._resolve_service_name", return_value="celery-worker"),
        ):
            meter.flush()

        mock_producer.produce.assert_called_once()
        produced_data = mock_producer.produce.call_args.kwargs["data"]
        assert set(produced_data.keys()) == WIRE_CONTRACT_FIELDS
        assert produced_data["product"] == "feature_flags"
        assert produced_data["team_id"] == 42
        assert produced_data["billable_unit"] == "flag_requests"
        assert produced_data["quantity"] == 1
        assert produced_data["system"] == "celery"
        assert produced_data["workload"] == "posthog.tasks.tasks.compute_feature_flag_metrics"
        assert produced_data["duration_ms"] == 150.5
        assert produced_data["environment"] == "prod-us"
        assert produced_data["service_name"] == "celery-worker"
        assert produced_data["count"] == 1

    def test_accumulates_quantity_duration_count_on_shared_key(self) -> None:
        meter = FinopsUsageMeter(enabled=True)
        for duration in [100, 200, 50]:
            meter.queue(
                FinopsUsageMeterInput(
                    product="shared",
                    billable_unit="events",
                    system="celery",
                    workload="posthog.tasks.tasks.calculate_cohort",
                    quantity=1,
                    duration_ms=duration,
                    count=1,
                )
            )

        mock_producer = MagicMock()
        with (
            patch("posthog.finops.usage_meter._get_producer", return_value=mock_producer),
            patch("posthog.finops.usage_meter._resolve_environment", return_value="dev"),
            patch("posthog.finops.usage_meter._resolve_service_name", return_value=""),
        ):
            meter.flush()

        mock_producer.produce.assert_called_once()
        data = mock_producer.produce.call_args.kwargs["data"]
        assert data["quantity"] == 3
        assert data["duration_ms"] == 350
        assert data["count"] == 3

    def test_buffer_cleared_after_flush(self) -> None:
        meter = FinopsUsageMeter(enabled=True)
        meter.queue(FinopsUsageMeterInput(product="shared", billable_unit="events", quantity=1))

        mock_producer = MagicMock()
        with (
            patch("posthog.finops.usage_meter._get_producer", return_value=mock_producer),
            patch("posthog.finops.usage_meter._resolve_environment", return_value="dev"),
            patch("posthog.finops.usage_meter._resolve_service_name", return_value=""),
        ):
            meter.flush()
            mock_producer.reset_mock()
            meter.flush()

        mock_producer.produce.assert_not_called()

    def test_flush_error_does_not_propagate(self) -> None:
        meter = FinopsUsageMeter(enabled=True)
        meter.queue(FinopsUsageMeterInput(product="shared", billable_unit="events", quantity=1))

        with patch("posthog.finops.usage_meter._get_producer", side_effect=RuntimeError("kafka down")):
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
        from posthog.finops.usage_meter import _resolve_environment

        with patch("posthog.settings.base_variables.CLOUD_DEPLOYMENT", cloud_deployment):
            assert _resolve_environment() == expected


class TestCeleryTaskProductMap:
    @parameterized.expand(
        [
            ("posthog.tasks.tasks.calculate_cohort", "shared", "events"),
            ("products.feature_flags.backend.tasks.compute_feature_flag_metrics", "feature_flags", "flag_requests"),
            ("posthog.tasks.tasks.redis_heartbeat", "platform-internal", "none"),
            ("posthog.tasks.exporter.export_asset", "shared", "shared"),
            (
                "products.error_tracking.backend.tasks.tasks.compute_error_tracking_recommendation",
                "error_tracking",
                "exceptions",
            ),
            (
                "products.web_analytics.backend.tasks.heatmap_screenshot.generate_heatmap_screenshot",
                "web_analytics",
                "events",
            ),
            ("posthog.email.send_canary_email", "platform_and_support", "none"),
            ("posthog.tasks.tasks.stop_surveys_reached_target", "surveys", "survey_responses"),
        ]
    )
    def test_resolves_known_task(self, task_name: str, expected_product: str, expected_billable_unit: str) -> None:
        result = resolve_celery_task_product(task_name)
        assert result == CeleryTaskProduct(expected_product, expected_billable_unit)

    def test_unknown_task_returns_fallback(self) -> None:
        result = resolve_celery_task_product("some.unknown.module.mystery_task")
        assert result == CeleryTaskProduct("unallocated", "shared")

    def test_bare_function_name_matches(self) -> None:
        result = resolve_celery_task_product("calculate_cohort")
        assert result.product == "shared"


class TestCeleryFinopsIntegration:
    def test_emit_finops_meter_disabled(self) -> None:
        from posthog.celery import _emit_finops_meter

        with patch("posthog.celery._finops_meter", None):
            _emit_finops_meter("posthog.tasks.tasks.calculate_cohort", {"team_id": 1}, 100.0, "celery")

    def test_emit_finops_meter_enabled(self) -> None:
        import structlog

        from posthog.celery import _emit_finops_meter

        mock_meter = MagicMock()
        with (
            patch("posthog.celery._finops_meter", mock_meter),
            structlog.contextvars.bound_contextvars(user_id=99),
        ):
            _emit_finops_meter(
                "posthog.tasks.tasks.calculate_cohort",
                {"team_id": 42},
                250.5,
                "celery",
            )

        mock_meter.queue.assert_called_once()
        queued_input = mock_meter.queue.call_args[0][0]
        assert queued_input.product == "shared"
        assert queued_input.billable_unit == "events"
        assert queued_input.team_id == 42
        assert queued_input.user_id == 99
        assert queued_input.system == "celery"
        assert queued_input.workload == "posthog.tasks.tasks.calculate_cohort"
        assert queued_input.resource_id == "celery"
        assert queued_input.duration_ms == 250.5
        assert queued_input.quantity == 1
        mock_meter.flush.assert_called_once()

    @parameterized.expand(
        [
            ({"team_id": 42}, 42),
            ({"team_id": 0}, 0),
            ({}, 0),
            (None, 0),
            ({"team_id": "not_int"}, 0),
            ({"team_id": True}, 0),
        ]
    )
    def test_extract_celery_team_id(self, kwargs: dict | None, expected: int) -> None:
        from posthog.celery import _extract_celery_team_id

        assert _extract_celery_team_id(kwargs) == expected

    def test_extract_celery_user_id_from_contextvars(self) -> None:
        import structlog

        from posthog.celery import _extract_celery_user_id

        with structlog.contextvars.bound_contextvars(user_id=123):
            assert _extract_celery_user_id() == 123

    def test_extract_celery_user_id_absent(self) -> None:
        import structlog

        from posthog.celery import _extract_celery_user_id

        structlog.contextvars.clear_contextvars()
        assert _extract_celery_user_id() == 0

    def test_extract_celery_user_id_non_int(self) -> None:
        import structlog

        from posthog.celery import _extract_celery_user_id

        with structlog.contextvars.bound_contextvars(user_id="not_an_int"):
            assert _extract_celery_user_id() == 0

    def test_emit_finops_meter_no_user_id_in_context(self) -> None:
        import structlog

        from posthog.celery import _emit_finops_meter

        mock_meter = MagicMock()
        structlog.contextvars.clear_contextvars()
        with patch("posthog.celery._finops_meter", mock_meter):
            _emit_finops_meter("posthog.tasks.tasks.calculate_cohort", {}, 100.0, "celery")

        queued_input = mock_meter.queue.call_args[0][0]
        assert queued_input.user_id == 0

    def test_emit_finops_meter_error_does_not_propagate(self) -> None:
        from posthog.celery import _emit_finops_meter

        mock_meter = MagicMock()
        mock_meter.queue.side_effect = RuntimeError("boom")
        with patch("posthog.celery._finops_meter", mock_meter):
            _emit_finops_meter("posthog.tasks.tasks.calculate_cohort", {}, 100.0, "celery")
