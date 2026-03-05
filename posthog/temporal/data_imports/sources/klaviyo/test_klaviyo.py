from datetime import UTC, date, datetime

from parameterized import parameterized

from posthog.temporal.data_imports.sources.klaviyo.klaviyo import _build_filter, _format_incremental_value, get_resource
from posthog.temporal.data_imports.sources.klaviyo.settings import KLAVIYO_ENDPOINTS


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


class TestBuildFilter:
    def test_incremental_only(self) -> None:
        config = KLAVIYO_ENDPOINTS["events"]
        result = _build_filter(config, "datetime", "2026-03-04T02:58:14.000Z")
        assert result == "greater-than(datetime,2026-03-04T02:58:14.000Z)"

    def test_base_filter_only(self) -> None:
        config = KLAVIYO_ENDPOINTS["email_campaigns"]
        result = _build_filter(config, None, None)
        assert result == "equals(messages.channel,'email')"

    def test_combined_base_and_incremental(self) -> None:
        config = KLAVIYO_ENDPOINTS["email_campaigns"]
        result = _build_filter(config, "updated_at", "2026-03-04T02:58:14.000Z")
        assert result == "and(equals(messages.channel,'email'),greater-than(updated_at,2026-03-04T02:58:14.000Z))"

    def test_no_filter(self) -> None:
        config = KLAVIYO_ENDPOINTS["metrics"]
        result = _build_filter(config, None, None)
        assert result is None


class TestGetResource:
    def test_events_incremental_uses_z_suffix(self) -> None:
        resource = get_resource(
            "events",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="datetime",
        )
        filter_value = resource["endpoint"]["params"]["filter"]
        assert "+00:00" not in filter_value
        assert filter_value == "greater-than(datetime,2026-03-04T02:58:14.000Z)"
