import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from parameterized import parameterized

from products.dashboards.backend.v2.buckets import (
    EVENTS_SETTLE,
    FAST_SETTLE,
    UNBOUNDED_RANGE_END,
    BucketContractError,
    BucketedQuery,
    BucketGrid,
    BucketStore,
    BucketStoreError,
    NotBucketable,
    SpanRows,
    assemble,
    check_bucketed,
)


def _local_hour(ts: datetime, tz: ZoneInfo) -> datetime:
    return ts.astimezone(tz).replace(minute=0, second=0, microsecond=0)


def _local_day(ts: datetime, tz: ZoneInfo) -> datetime:
    return ts.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0, fold=0)


class _Events:
    """A table of event timestamps and a query over it that counts per bucket, as ClickHouse would answer
    `SELECT toStartOfHour(timestamp), count() ... WHERE {filters} GROUP BY 1 ORDER BY 1`."""

    def __init__(self, unit: str, tz: ZoneInfo, row_limit: int | None = None, own_limit: bool = False) -> None:
        self.unit = unit
        self.tz = tz
        self.timestamps: list[datetime] = []
        self.runs: list[tuple[datetime, datetime]] = []
        # Rows past `row_limit` are cut off: with hasMore like the paginator, or silently like the query's own LIMIT.
        self.row_limit = row_limit
        self.own_limit = own_limit

    def bucket(self, ts: datetime) -> datetime:
        return _local_hour(ts, self.tz) if self.unit == "hour" else _local_day(ts, self.tz)

    def whole(self, start: datetime, end: datetime) -> list[list]:
        counts: dict[datetime, int] = {}
        for ts in self.timestamps:
            if start <= ts < end:
                counts[self.bucket(ts)] = counts.get(self.bucket(ts), 0) + 1
        return [[bucket, count] for bucket, count in sorted(counts.items())]

    def fetch(self, start: datetime, end: datetime) -> SpanRows:
        self.runs.append((start, end))
        rows = self.whole(start, end)
        cut = self.row_limit is not None and len(rows) > self.row_limit
        return SpanRows(
            columns=["t", "count"],
            types=[],
            rows=rows[: self.row_limit] if cut else rows,
            has_more=cut and not self.own_limit,
        )


def _as_json(rows: list[list]) -> list[list]:
    return [[bucket.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), count] for bucket, count in rows]


def _answer_json(rows: list[list]) -> list[list]:
    return [
        [datetime.fromisoformat(bucket).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), count] for bucket, count in rows
    ]


def _query(unit: str) -> BucketedQuery:
    return BucketedQuery(unit=unit, size=1, settle=EVENTS_SETTLE, order="ASC", limit=None)  # type: ignore[arg-type]


class TestAssembleBuckets(SimpleTestCase):
    def _store(self) -> BucketStore:
        return BucketStore(f"test_buckets:{uuid.uuid4().hex}")

    def _run(
        self,
        events: _Events,
        store: BucketStore,
        date_from: datetime,
        date_to: datetime,
        now: datetime,
        limit: int = 10_000,
        row_cap: int | None = None,
    ):
        grid = BucketGrid(unit=events.unit, size=1, tz=events.tz)  # type: ignore[arg-type]
        return assemble(
            query=_query(events.unit),
            grid=grid,
            date_from=date_from,
            date_to=date_to,
            now=now,
            store=store,
            fetch=events.fetch,
            limit=limit,
            row_cap=row_cap,
        )

    @parameterized.expand(
        [
            ("utc_hours", "hour", "UTC", datetime(2026, 3, 5, tzinfo=UTC)),
            ("half_hour_offset_hours", "hour", "Asia/Kolkata", datetime(2026, 3, 5, tzinfo=UTC)),
            # The range crosses the spring-forward day, a 23-hour day in New York.
            ("dst_days", "day", "America/New_York", datetime(2026, 3, 1, tzinfo=UTC)),
            ("dst_hours", "hour", "America/New_York", datetime(2026, 3, 7, tzinfo=UTC)),
        ]
    )
    def test_a_warm_refresh_reruns_only_unfinished_buckets_and_matches_a_whole_run(
        self, _name: str, unit: str, tz_name: str, start: datetime
    ) -> None:
        tz = ZoneInfo(tz_name)
        events = _Events(unit, tz)
        span = timedelta(days=12) if unit == "day" else timedelta(days=3)
        step = timedelta(hours=5) if unit == "day" else timedelta(minutes=37)
        events.timestamps = [start + step * i for i in range(int(span / step))]
        now = start + span - timedelta(minutes=10)
        date_from = _local_day(start, tz).astimezone(UTC) + timedelta(days=1)
        store = self._store()

        first = self._run(events, store, date_from, now, now)
        self.assertEqual(_answer_json(first.rows), _as_json(events.whole(date_from, now)))

        # An hour later rows have landed in the newest buckets, the one that was still filling included.
        later = now + timedelta(hours=1)
        events.timestamps += [
            now - timedelta(minutes=55),
            now - timedelta(minutes=5),
            now + timedelta(minutes=20),
            later - timedelta(minutes=1),
        ]
        events.runs.clear()
        second = self._run(events, store, date_from, later, later)

        self.assertEqual(_answer_json(second.rows), _as_json(events.whole(date_from, later)))
        self.assertGreater(second.stored_buckets, 0)
        settled_before = BucketGrid(unit=unit, size=1, tz=tz).floor(now - EVENTS_SETTLE)  # type: ignore[arg-type]
        self.assertTrue(all(run_start >= settled_before for run_start, _end in events.runs), events.runs)

    def test_a_range_that_starts_mid_bucket_counts_only_its_part_of_the_first_bucket(self) -> None:
        tz = ZoneInfo("Europe/Berlin")
        events = _Events("hour", tz)
        start = datetime(2026, 5, 1, tzinfo=UTC)
        events.timestamps = [start + timedelta(minutes=7 * i) for i in range(1000)]
        now = start + timedelta(minutes=7 * 1000)
        store = self._store()
        for date_from in (start + timedelta(hours=5, minutes=13), start + timedelta(hours=6, minutes=13)):
            answer = self._run(events, store, date_from, now, now)
            self.assertEqual(_answer_json(answer.rows), _as_json(events.whole(date_from, now)))

    def test_a_previous_period_extends_the_same_store_instead_of_rerunning_it(self) -> None:
        tz = ZoneInfo("UTC")
        events = _Events("hour", tz)
        start = datetime(2026, 5, 1, tzinfo=UTC)
        events.timestamps = [start + timedelta(minutes=11 * i) for i in range(2000)]
        now = start + timedelta(days=14)
        store = self._store()
        self._run(events, store, now - timedelta(days=7), now, now)
        events.runs.clear()

        previous = self._run(events, store, now - timedelta(days=14), now - timedelta(days=7), now)

        self.assertEqual(
            _answer_json(previous.rows), _as_json(events.whole(now - timedelta(days=14), now - timedelta(days=7)))
        )
        self.assertEqual(events.runs, [(now - timedelta(days=14), now - timedelta(days=7))])

    def test_buckets_off_the_project_timezone_grid_are_refused(self) -> None:
        events = _Events("hour", ZoneInfo("UTC"))
        start = datetime(2026, 5, 1, tzinfo=UTC)
        events.timestamps = [start + timedelta(minutes=10 * i) for i in range(100)]
        grid = BucketGrid(unit="hour", size=1, tz=ZoneInfo("Asia/Kolkata"))
        with self.assertRaises(BucketContractError):
            assemble(
                query=_query("hour"),
                grid=grid,
                date_from=start,
                date_to=start + timedelta(hours=10),
                now=start + timedelta(hours=10),
                store=self._store(),
                fetch=events.fetch,
                limit=10_000,
                row_cap=None,
            )

    def test_a_query_with_its_own_limit_stores_only_whole_spans(self) -> None:
        # LIMIT 10 reports no hasMore, so a run that returns 10 rows may have been cut short.
        events = _Events("hour", ZoneInfo("UTC"), row_limit=10, own_limit=True)
        start = datetime(2026, 5, 1, tzinfo=UTC)
        events.timestamps = [start + timedelta(minutes=20 * i) for i in range(3 * 48)]
        now = start + timedelta(hours=50)
        store = self._store()

        warm = self._run(events, store, start, start + timedelta(hours=48), now, limit=10, row_cap=10)
        later = self._run(
            events, store, start + timedelta(hours=24), start + timedelta(hours=36), now, limit=10, row_cap=10
        )

        self.assertEqual(_answer_json(warm.rows), _as_json(events.whole(start, start + timedelta(hours=48))[:10]))
        self.assertEqual(
            _answer_json(later.rows),
            _as_json(events.whole(start + timedelta(hours=24), start + timedelta(hours=36))[:10]),
        )

    def test_a_range_with_no_end_splits_at_now_instead_of_walking_to_its_far_end(self) -> None:
        events = _Events("hour", ZoneInfo("UTC"), row_limit=4)
        start = datetime(2026, 5, 1, tzinfo=UTC)
        events.timestamps = [start + timedelta(minutes=10 * i) for i in range(6 * 6)]
        now = start + timedelta(hours=6)

        answer = self._run(events, self._store(), start, UNBOUNDED_RANGE_END, now)

        self.assertEqual(_answer_json(answer.rows), _as_json(events.whole(start, now)))
        self.assertLessEqual(len(events.runs), 8, events.runs)

    def test_a_range_ending_mid_bucket_before_the_store_counts_each_bucket_once(self) -> None:
        events = _Events("hour", ZoneInfo("UTC"))
        day = datetime(2026, 5, 1, tzinfo=UTC)
        events.timestamps = [day + timedelta(minutes=7 * i) for i in range(400)]
        now = day + timedelta(days=2)
        store = self._store()
        self._run(events, store, day + timedelta(hours=12), now, now)

        earlier = self._run(events, store, day, day + timedelta(hours=11, minutes=30), now)

        self.assertEqual(_answer_json(earlier.rows), _as_json(events.whole(day, day + timedelta(hours=11, minutes=30))))

    def test_a_store_that_expires_while_a_range_runs_is_not_read_as_empty_buckets(self) -> None:
        class _ExpiresMidRun(BucketStore):
            def read(self, buckets):
                return None, {}

        events = _Events("hour", ZoneInfo("UTC"))
        start = datetime(2026, 5, 1, tzinfo=UTC)
        events.timestamps = [start + timedelta(minutes=13 * i) for i in range(400)]
        now = start + timedelta(days=3)
        store = _ExpiresMidRun(f"test_buckets:{uuid.uuid4().hex}")
        self._run(events, store, start, now, now)

        with self.assertRaises(BucketStoreError):
            self._run(events, store, start, now + timedelta(hours=2), now + timedelta(hours=2))


class TestCheckBucketed(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "hourly_events",
                "SELECT toStartOfHour(timestamp) AS t, event, count() FROM events WHERE {filters} GROUP BY t, event ORDER BY t",
                ("hour", 1, EVENTS_SETTLE),
            ),
            (
                "fifteen_minute_logs",
                "SELECT toStartOfInterval(timestamp, INTERVAL 15 MINUTE), count() FROM logs WHERE {filters} GROUP BY 1",
                ("minute", 15, FAST_SETTLE),
            ),
            (
                "date_range_placeholders",
                "SELECT toStartOfDay(timestamp) AS d, uniq(person_id) FROM events "
                "WHERE timestamp >= {filters.dateRange.from} AND timestamp < {filters.dateRange.to} GROUP BY d",
                ("day", 1, EVENTS_SETTLE),
            ),
        ]
    )
    def test_qualifies(self, _name: str, query: str, expected: tuple) -> None:
        checked = check_bucketed(query)
        self.assertEqual((checked.unit, checked.size, checked.settle), expected)

    @parameterized.expand(
        [
            (
                "not_bucket_first",
                "SELECT count(), toStartOfHour(timestamp) AS t FROM events WHERE {filters} GROUP BY t",
                "first column",
            ),
            ("no_date_filter", "SELECT toStartOfHour(timestamp) AS t, count() FROM events GROUP BY t", "{filters}"),
            (
                "window",
                "SELECT toStartOfHour(timestamp) AS t, sum(count()) OVER (ORDER BY t) FROM events WHERE {filters} GROUP BY t",
                "window function",
            ),
            (
                "clock",
                "SELECT toStartOfHour(timestamp) AS t, count() FROM events WHERE {filters} AND timestamp > now() - INTERVAL 1 DAY GROUP BY t",
                "clock",
            ),
            (
                "whole_range_aggregate",
                "SELECT toStartOfHour(timestamp) AS t, count() FROM events WHERE {filters}",
                "GROUP BY",
            ),
            (
                "not_grouped_by_bucket",
                "SELECT toStartOfHour(timestamp) AS t, count() FROM events WHERE {filters} GROUP BY event",
                "GROUP BY the bucket",
            ),
            (
                "ordered_by_count",
                "SELECT toStartOfHour(timestamp) AS t, count() AS c FROM events WHERE {filters} GROUP BY t ORDER BY c DESC",
                "ORDER BY",
            ),
            (
                "clock_alias",
                "SELECT toStartOfHour(timestamp) AS t, count() FROM events WHERE {filters} "
                "AND timestamp > current_timestamp() - INTERVAL 1 DAY GROUP BY t",
                "clock",
            ),
            (
                "range_in_select",
                "SELECT toStartOfHour(timestamp) AS t, {filters.dateRange.from} AS since, count() FROM events "
                "WHERE {filters} GROUP BY t, since",
                "outside its WHERE",
            ),
            (
                "subquery_over_range",
                "SELECT toStartOfHour(timestamp) AS t, count() FROM events WHERE {filters} AND person_id IN "
                "(SELECT person_id FROM events WHERE {filters} GROUP BY person_id HAVING count() > 5) GROUP BY t",
                "subquery",
            ),
            (
                "bucket_in_utc",
                "SELECT toStartOfHour(timestamp, 'UTC') AS t, count() FROM events WHERE {filters} GROUP BY t",
                "first column",
            ),
            (
                "seven_minutes",
                "SELECT toStartOfInterval(timestamp, INTERVAL 7 MINUTE) AS t, count() FROM events WHERE {filters} GROUP BY t",
                "first column",
            ),
        ]
    )
    def test_says_why_a_query_does_not_qualify(self, _name: str, query: str, reason: str) -> None:
        with self.assertRaises(NotBucketable) as caught:
            check_bucketed(query)
        self.assertIn(reason, str(caught.exception))
