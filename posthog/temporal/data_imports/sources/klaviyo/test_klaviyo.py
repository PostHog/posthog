from datetime import UTC, date, datetime

from freezegun import freeze_time

from parameterized import parameterized

from posthog.temporal.data_imports.sources.klaviyo.klaviyo import (
    _build_filter,
    _build_initial_params,
    _clamp_future_value_to_now,
    _format_incremental_value,
)
from posthog.temporal.data_imports.sources.klaviyo.settings import KLAVIYO_ENDPOINTS, KlaviyoEndpointConfig
from posthog.temporal.data_imports.sources.klaviyo.source import KlaviyoSource


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

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_cursor_is_clamped_to_now(self) -> None:
        # A future-dated cursor would otherwise build greater-than(datetime,<future>),
        # which Klaviyo rejects with a 400 and wedges every subsequent sync.
        config = KLAVIYO_ENDPOINTS["events"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2027, 2, 5, 21, 46, 42, tzinfo=UTC),
            incremental_field="datetime",
        )
        assert params["filter"] == "greater-than(datetime,2026-06-15T12:00:00.000Z)"

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_cursor_is_not_modified(self) -> None:
        config = KLAVIYO_ENDPOINTS["events"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="datetime",
        )
        assert params["filter"] == "greater-than(datetime,2026-03-04T02:58:14.000Z)"


class TestClampFutureValueToNow:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, 21, 46, 42, tzinfo=UTC)) == datetime(
            2026, 6, 15, 12, 0, 0, tzinfo=UTC
        )

    @freeze_time("2026-06-15T12:00:00Z")
    def test_naive_future_datetime_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, 21, 46, 42)) == datetime(
            2026, 6, 15, 12, 0, 0, tzinfo=UTC
        )

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_datetime_is_unchanged(self) -> None:
        value = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        assert _clamp_future_value_to_now(value) == value

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_date_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(date(2027, 2, 5)) == date(2026, 6, 15)

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_date_is_unchanged(self) -> None:
        assert _clamp_future_value_to_now(date(2026, 3, 4)) == date(2026, 3, 4)

    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("some-cursor-value") == "some-cursor-value"


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            # 401/403 surfaced as a requests HTTPError when `fetch_page` calls `raise_for_status()`.
            # The per-request path/query/timestamp varies, but the status text and base host are stable.
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://a.klaviyo.com/api/events?filter=greater-than(datetime,2026-06-15T13:03:18.000Z)",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://a.klaviyo.com/api/metrics",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = KlaviyoSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            # Transient/infra errors and server-side failures must stay retryable.
            ("read_timeout", "HTTPSConnectionPool(host='a.klaviyo.com', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://a.klaviyo.com/api/events",
            ),
            ("connection_reset", "Connection reset by peer"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable_errors = KlaviyoSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)
