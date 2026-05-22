from datetime import UTC, datetime, timedelta

from parameterized import parameterized

from posthog.temporal.session_replay.count_playlist_items.counting_logic import is_session_unexpired, parse_expiry


class TestParseExpiry:
    @parameterized.expand(
        [
            ("none_returns_none", None, None),
            ("empty_string_returns_none", "", None),
            ("garbage_returns_none", "not-a-date", None),
        ]
    )
    def test_invalid_inputs(self, _name: str, value: str | None, expected: datetime | None):
        assert parse_expiry(value) is None

    def test_valid_iso_with_tz(self):
        result = parse_expiry("2026-04-10T12:00:00+00:00")
        assert result == datetime(2026, 4, 10, 12, 0, 0, tzinfo=UTC)

    def test_naive_datetime_gets_tz(self):
        result = parse_expiry("2026-04-10T12:00:00")
        assert result is not None
        assert result.tzinfo is not None


class TestIsSessionUnexpired:
    now = datetime(2026, 4, 9, 12, 0, 0, tzinfo=UTC)

    @parameterized.expand(
        [
            ("none_expiry_is_unexpired", None, True),
            ("future_expiry_is_unexpired", (now + timedelta(days=1)).isoformat(), True),
            ("exact_now_is_unexpired", now.isoformat(), True),
            ("past_expiry_is_expired", (now - timedelta(days=1)).isoformat(), False),
            ("garbage_expiry_is_expired", "not-a-date", False),
        ]
    )
    def test_expiry_cases(self, _name: str, expiry: str | None, expected: bool):
        assert is_session_unexpired(expiry, self.now) == expected
