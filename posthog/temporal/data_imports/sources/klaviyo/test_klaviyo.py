from datetime import UTC, date, datetime

from parameterized import parameterized

from posthog.temporal.data_imports.sources.klaviyo.klaviyo import (
    _build_filter,
    _build_initial_params,
    _format_incremental_value,
)
from posthog.temporal.data_imports.sources.klaviyo.settings import KLAVIYO_ENDPOINTS, KlaviyoEndpointConfig


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (
                "datetime_with_microseconds",
                datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC),
                "2026-01-15T10:30:45.123Z",
            ),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "some-cursor-value", "some-cursor-value"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected

    def test_no_plus_zero_offset_in_output(self) -> None:
        result = _format_incremental_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))
        assert "+00:00" not in result


class TestBuildFilter:
    @parameterized.expand(
        [
            (
                "incremental_only",
                KLAVIYO_ENDPOINTS["events"],
                "datetime",
                "2026-03-04T02:58:14.000Z",
                "greater-than(datetime,2026-03-04T02:58:14.000Z)",
            ),
            (
                "base_filter_only",
                KLAVIYO_ENDPOINTS["email_campaigns"],
                None,
                None,
                "equals(messages.channel,'email')",
            ),
            (
                "combined_base_and_incremental",
                KLAVIYO_ENDPOINTS["email_campaigns"],
                "updated_at",
                "2026-03-04T02:58:14.000Z",
                "and(equals(messages.channel,'email'),greater-than(updated_at,2026-03-04T02:58:14.000Z))",
            ),
            ("no_filter", KLAVIYO_ENDPOINTS["metrics"], None, None, None),
        ]
    )
    def test_build_filter(
        self, _name: str, config: KlaviyoEndpointConfig, field: str | None, value: str | None, expected: str | None
    ) -> None:
        assert _build_filter(config, field, value) == expected


class TestBuildInitialParams:
    def test_events_incremental_uses_z_suffix(self) -> None:
        config = KLAVIYO_ENDPOINTS["events"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="datetime",
        )
        assert "+00:00" not in params["filter"]
        assert params["filter"] == "greater-than(datetime,2026-03-04T02:58:14.000Z)"

    def test_lookback_window_uses_z_suffix(self) -> None:
        config = KLAVIYO_ENDPOINTS["events"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="datetime",
        )
        assert "filter" in params
        assert "+00:00" not in params["filter"]
        assert params["filter"].endswith("Z)")
