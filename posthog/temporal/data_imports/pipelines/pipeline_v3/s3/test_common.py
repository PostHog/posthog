from datetime import UTC, datetime, timedelta, timezone

from parameterized import parameterized

from posthog.temporal.data_imports.pipelines.pipeline_v3.s3.common import get_date_partition


class TestGetDatePartition:
    @parameterized.expand(
        [
            ("midday_utc", datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC), "dt=2026-05-22"),
            ("just_before_midnight_utc", datetime(2026, 5, 22, 23, 59, 59, tzinfo=UTC), "dt=2026-05-22"),
            ("just_after_midnight_utc", datetime(2026, 5, 23, 0, 0, 1, tzinfo=UTC), "dt=2026-05-23"),
        ]
    )
    def test_formats_utc_datetime(self, _name: str, dt: datetime, expected: str) -> None:
        assert get_date_partition(dt) == expected

    def test_converts_non_utc_to_utc_date(self) -> None:
        la = timezone(timedelta(hours=-7))
        dt = datetime(2026, 5, 22, 19, 0, 0, tzinfo=la)

        assert get_date_partition(dt) == "dt=2026-05-23"

    def test_same_partition_across_midnight_when_pinned(self) -> None:
        created_at = datetime(2026, 5, 22, 23, 59, 0, tzinfo=UTC)

        partition_at_start = get_date_partition(created_at)
        partition_an_hour_later = get_date_partition(created_at)

        assert partition_at_start == partition_an_hour_later == "dt=2026-05-22"
