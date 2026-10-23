from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.printer.utils import prepare_and_print_ast

from products.ai_observability.backend.facade.api import (
    evaluations_period,
    get_evaluation_runs,
    get_evaluations_overview,
)
from products.ai_observability.backend.logic.evaluations.overview_queries import (
    CategoryBucketCount,
    load_bucket_counts,
    load_category_counts,
    run_evaluation_query,
)
from products.ai_observability.backend.logic.evaluations.pass_filters import build_pass_rules
from products.ai_observability.backend.logic.evaluations.period import (
    InvalidPeriodError,
    OverviewPeriod,
    PeriodBounds,
    overview_period,
)
from products.ai_observability.backend.models.evaluations import Evaluation

PERIOD = OverviewPeriod(
    start=datetime(2026, 3, 8, tzinfo=UTC),
    end=datetime(2026, 3, 15, tzinfo=UTC),
    previous_start=datetime(2026, 3, 1, tzinfo=UTC),
    previous_end=datetime(2026, 3, 8, tzinfo=UTC),
    interval="day",
    buckets=tuple(datetime(2026, 3, day, tzinfo=UTC) for day in range(8, 15)),
)


NEW_YORK = ZoneInfo("America/New_York")


def _midnight(day: int) -> datetime:
    return datetime(2026, 3, day, tzinfo=UTC)


@parameterized.expand(
    [
        # Clocks spring forward on March 8, so 48 real hours span 49 hours on the wall.
        ("spring_forward", datetime(2026, 3, 9, 12, tzinfo=UTC), 48),
        # Clocks fall back on November 1, so 24 real hours span 23 hours on the wall.
        ("fall_back", datetime(2026, 11, 1, 18, tzinfo=UTC), 24),
    ]
)
def test_rolling_hours_keep_their_real_length_across_daylight_saving(_name: str, now: datetime, hours: int) -> None:
    length = timedelta(hours=hours)
    period = overview_period((now - length).astimezone(NEW_YORK), now.astimezone(NEW_YORK), now, NEW_YORK)

    assert period.interval == "hour"
    assert len(period.buckets) == hours
    assert (period.previous_start, period.previous_end) == (now - 2 * length, now - length)


@parameterized.expand(
    [
        ("end before start", date(2026, 3, 10), date(2026, 3, 9), "date_from"),
        ("91 days", date(2026, 8, 4), date(2026, 11, 2), "date_from"),
        ("last day of year 9999", None, date(9999, 12, 31), "out of range"),
        ("first day of year 1", None, date(1, 1, 1), "out of range"),
        # Clocks fall back on November 1, so these 90 days are 2161 hours long.
        ("90 days across daylight saving", date(2026, 8, 5), date(2026, 11, 2), None),
        (
            "90 days of instants",
            datetime(2026, 8, 5, tzinfo=UTC),
            datetime(2026, 11, 3, tzinfo=UTC),
            None,
        ),
        (
            "an instant past 90 days",
            datetime(2026, 8, 5, tzinfo=UTC),
            datetime(2026, 11, 3, 0, 0, 1, tzinfo=UTC),
            "date_from",
        ),
    ]
)
def test_period_from_request(
    _name: str, date_from: date | datetime | None, date_to: date | datetime, error: str | None
) -> None:
    if error is None:
        PeriodBounds.from_request(date_from, date_to, NEW_YORK)
        return
    with pytest.raises(InvalidPeriodError) as raised:
        PeriodBounds.from_request(date_from, date_to, NEW_YORK)
    assert (raised.value.field or "out of range") == error


class TestEvaluationsOverviewQueries(ClickhouseTestMixin, BaseTest):
    def _judge(self) -> Evaluation:
        return Evaluation.objects.create(
            team=self.team,
            name="Judge",
            evaluation_type="hog",
            evaluation_config={"source": "return true"},
            output_type="boolean",
            output_config={},
        )

    def _run(self, evaluation: Evaluation, timestamp: str, **properties: object) -> None:
        _create_event(
            team=self.team,
            event="$ai_evaluation",
            distinct_id="user-1",
            timestamp=timestamp,
            properties={"$ai_evaluation_id": str(evaluation.id), **properties},
        )

    @parameterized.expand(
        [
            ("one query per kind", 50_000, 25_000, 2),
            ("a batch per evaluation", 50_000, 1, 3),
            # A full page splits its batch, down to one evaluation, which pages through its own rows.
            ("full pages", 2, 50_000, 8),
        ]
    )
    def test_groups_runs_by_evaluation_day_and_period(
        self, _name: str, page_size: int, batch_rows: int, queries: int
    ) -> None:
        judge = self._judge()
        topic = Evaluation.objects.create(
            team=self.team,
            name="Topic",
            evaluation_type="hog",
            evaluation_config={"source": "return []"},
            output_type="categorical",
            output_config={
                "options": [{"key": "billing", "label": "Billing"}, {"key": "bug", "label": "Bug"}],
                "selection_mode": "multiple",
            },
        )
        unrequested = Evaluation.objects.create(
            team=self.team, name="Not asked for", evaluation_type="hog", output_type="boolean", output_config={}
        )
        categorical = {"$ai_evaluation_result_type": "categorical", "$ai_evaluation_applicable": True}
        self._run(judge, "2026-03-09T10:00:00Z", **{"$ai_evaluation_result": True})
        self._run(judge, "2026-03-09T11:00:00Z", **{"$ai_evaluation_result": False})
        self._run(judge, "2026-03-09T12:00:00Z", **{"$ai_evaluation_applicable": False})
        skipped = {"$ai_evaluation_result": False, "$ai_evaluation_skipped": True}
        self._run(judge, "2026-03-10T10:00:00Z", **skipped, **{"$ai_evaluation_skip_reason": "hog_input_error"})
        self._run(judge, "2026-03-10T11:00:00Z", **skipped, **{"$ai_evaluation_skip_reason": "trace_not_found"})
        self._run(judge, "2026-03-02T10:00:00Z", **{"$ai_evaluation_result": True})
        self._run(judge, "2026-03-07T23:00:00Z", **{"$ai_evaluation_result": True})
        self._run(judge, "2026-02-28T23:00:00Z", **{"$ai_evaluation_result": True})
        self._run(
            topic, "2026-03-09T10:00:00Z", **categorical, **{"$ai_evaluation_categorical_result": ["billing", "bug"]}
        )
        self._run(topic, "2026-03-09T11:00:00Z", **categorical, **{"$ai_evaluation_categorical_result": []})
        self._run(topic, "2026-03-03T10:00:00Z", **categorical, **{"$ai_evaluation_categorical_result": ["bug"]})
        self._run(unrequested, "2026-03-09T10:00:00Z", **{"$ai_evaluation_result": True})
        flush_persons_and_events()

        ids = [str(judge.id), str(topic.id)]
        module = "products.ai_observability.backend.logic.evaluations.overview_queries"
        with (
            patch(f"{module}.PAGE_SIZE", page_size),
            patch(f"{module}.BATCH_ROWS", batch_rows),
            patch(f"{module}.run_evaluation_query", wraps=run_evaluation_query) as run,
        ):
            bucket_counts = load_bucket_counts(self.team, None, PERIOD, ids, build_pass_rules(self.team.pk, ids))
            category_counts = load_category_counts(self.team, None, PERIOD, {str(topic.id): 2})
        counts = {
            (row.evaluation_id, row.bucket): (row.passed, row.failed, row.not_applicable, row.skipped, row.categorized)
            for row in bucket_counts
        }
        categories = sorted(category_counts, key=lambda row: (row.bucket or datetime.min.replace(tzinfo=UTC), row.key))

        assert counts == {
            (str(judge.id), _midnight(9)): (1, 1, 1, 0, 0),
            (str(judge.id), _midnight(10)): (0, 0, 0, 2, 0),
            (str(judge.id), None): (2, 0, 0, 0, 0),
            (str(topic.id), _midnight(9)): (0, 0, 0, 0, 2),
            (str(topic.id), None): (0, 0, 0, 0, 1),
        }
        assert categories == [
            CategoryBucketCount(evaluation_id=str(topic.id), bucket=None, key="bug", runs=1),
            CategoryBucketCount(evaluation_id=str(topic.id), bucket=_midnight(9), key="", runs=1),
            CategoryBucketCount(evaluation_id=str(topic.id), bucket=_midnight(9), key="billing", runs=1),
            CategoryBucketCount(evaluation_id=str(topic.id), bucket=_midnight(9), key="bug", runs=1),
        ]
        assert run.call_count == queries

    @time_machine.travel(datetime(2026, 3, 10, 3, 0, tzinfo=UTC), tick=False)
    def test_periods_follow_the_project_timezone_and_a_running_day(self) -> None:
        self.team.timezone = "Asia/Tokyo"
        self.team.save()
        judge = self._judge()
        # Now is 12:00 on March 10 in Tokyo, so the previous period runs from March 7 to 12:00 on March 8.
        for timestamp in (
            "2026-03-06T14:00:00Z",  # 23:00 March 6, before the previous period
            "2026-03-06T16:00:00Z",  # 01:00 March 7
            "2026-03-08T02:00:00Z",  # 11:00 March 8
            "2026-03-08T05:00:00Z",  # 14:00 March 8, later in the day than now
            "2026-03-08T16:00:00Z",  # 01:00 March 9
            "2026-03-09T16:00:00Z",  # 01:00 March 10
        ):
            self._run(judge, timestamp, **{"$ai_evaluation_result": True})
        flush_persons_and_events()

        overview = get_evaluations_overview(
            self.team,
            None,
            [str(judge.id)],
            evaluations_period(self.team, date(2026, 3, 9), date(2026, 3, 10)),
        )

        [row] = overview.evaluations
        # Two whole days are short enough for hourly buckets, which start on Tokyo's hours.
        assert overview.interval == "hour"
        assert overview.buckets[0] == datetime(2026, 3, 9, tzinfo=ZoneInfo("Asia/Tokyo"))
        assert [index for index, volume in enumerate(row.trend.volume) if volume] == [1, 25]
        assert row.previous_graded_count == 2

    @time_machine.travel(datetime(2026, 3, 12, 12, 0, tzinfo=UTC), tick=False)
    def test_days_follow_the_project_timezone_when_the_team_turns_off_converting_to_it(self) -> None:
        self.team.timezone = "America/New_York"
        self.team.modifiers = {"convertToProjectTimezone": False}
        self.team.save()
        judge = self._judge()
        # 22:00 on March 9 in New York, already March 10 in UTC.
        self._run(judge, "2026-03-10T02:00:00Z", **{"$ai_evaluation_result": True})
        flush_persons_and_events()

        overview = get_evaluations_overview(
            self.team,
            None,
            [str(judge.id)],
            evaluations_period(self.team, date(2026, 3, 8), date(2026, 3, 11)),
        )

        [row] = overview.evaluations
        assert overview.interval == "day"
        assert row.trend.volume == [0, 1, 0, 0]

    @parameterized.expand(
        [
            # 01:30 on November 1 in New York, before and after the clocks fall back.
            ("new_york_fall_back", "America/New_York", datetime(2026, 11, 1, 18, tzinfo=UTC), 24, ["05:30", "06:30"]),
            # Lord Howe moves its clocks by 30 minutes on October 4, so from then on the buckets start at half past
            # the local hour, and 01:10 and 01:40 on October 5 fall in different buckets.
            (
                "lord_howe_spring_forward",
                "Australia/Lord_Howe",
                datetime(2026, 10, 4, 20, tzinfo=UTC),
                48,
                ["2026-10-03T10:00", "2026-10-04T14:10", "2026-10-04T14:40"],
            ),
            ("kolkata_half_hour_offset", "Asia/Kolkata", datetime(2026, 3, 10, 12, tzinfo=UTC), 24, ["05:15", "06:45"]),
            # 09:59 and 10:01 in Kathmandu, either side of an hour that starts at a quarter past in UTC.
            (
                "kathmandu_quarter_hour_offset",
                "Asia/Kathmandu",
                datetime(2026, 3, 10, 12, tzinfo=UTC),
                24,
                ["04:14", "04:16"],
            ),
        ]
    )
    def test_every_hourly_run_lands_in_the_trend(
        self, _name: str, timezone: str, now: datetime, hours: int, times: list[str]
    ) -> None:
        self.team.timezone = timezone
        self.team.save()
        judge = self._judge()
        for at in times:
            timestamp = at if "T" in at else f"{now.date().isoformat()}T{at}"
            self._run(judge, f"{timestamp}:00Z", **{"$ai_evaluation_result": True})
        flush_persons_and_events()

        with time_machine.travel(now, tick=False):
            overview = get_evaluations_overview(
                self.team, None, [str(judge.id)], PeriodBounds(start=now - timedelta(hours=hours), end=now)
            )

        [row] = overview.evaluations
        assert overview.interval == "hour"
        assert [volume for volume in row.trend.volume if volume] == [1] * len(times)
        assert row.graded_count == len(times)

    @time_machine.travel(datetime(2026, 11, 1, 18, 0, tzinfo=UTC), tick=False)
    def test_a_window_inside_a_repeated_daylight_saving_hour_reads_its_runs(self) -> None:
        self.team.timezone = "America/New_York"
        self.team.save()
        judge = self._judge()
        # 01:00 on November 1 in New York after the clocks fall back, between 01:40 before and 01:20 after it.
        self._run(judge, "2026-11-01T06:00:00Z", **{"$ai_evaluation_result": False})
        flush_persons_and_events()
        period = PeriodBounds(
            start=datetime(2026, 11, 1, 5, 40, tzinfo=UTC), end=datetime(2026, 11, 1, 6, 20, tzinfo=UTC)
        )

        overview = get_evaluations_overview(self.team, None, [str(judge.id)], period)
        runs = get_evaluation_runs(self.team, None, str(judge.id), period, "failed", 5)

        assert overview.evaluations[0].graded_count == 1
        assert len(runs.results) == 1

    def test_query_size_does_not_grow_with_the_number_of_evaluations(self) -> None:
        def printed_size(count: int) -> int:
            Evaluation.objects.filter(team=self.team).delete()
            evaluations = Evaluation.objects.bulk_create(
                Evaluation(
                    team=self.team,
                    name=f"Score {index}",
                    evaluation_type="hog",
                    output_type="numeric",
                    output_config={"passing_rule": {"operator": "gte", "threshold": index}},
                )
                for index in range(count)
            )
            ids = [str(evaluation.id) for evaluation in evaluations]
            with patch(
                "products.ai_observability.backend.logic.evaluations.overview_queries.execute_hogql_query"
            ) as execute:
                execute.return_value.results = []
                load_bucket_counts(self.team, None, PERIOD, ids, build_pass_rules(self.team.pk, ids))
            context = HogQLContext(
                team_id=self.team.pk,
                team=self.team,
                enable_select_queries=True,
                database=Database.create_for_posthog_tables(self.team),
            )
            sql, _ = prepare_and_print_ast(execute.call_args.kwargs["query"], context, "clickhouse")
            return len(sql)

        assert printed_size(300) < printed_size(10) * 1.1

    @time_machine.travel(datetime(2026, 3, 10, 12, 30, tzinfo=UTC), tick=False)
    def test_a_day_or_shorter_buckets_by_hour_against_the_hours_before(self) -> None:
        judge = self._judge()
        for timestamp in (
            "2026-03-08T12:00:00Z",  # before the previous 24 hours
            "2026-03-08T13:00:00Z",  # previous 24 hours
            "2026-03-09T12:00:00Z",  # previous 24 hours, in the hour the current period starts
            "2026-03-09T12:45:00Z",
            "2026-03-09T13:10:00Z",
            "2026-03-09T13:50:00Z",
            "2026-03-10T12:10:00Z",
        ):
            self._run(judge, timestamp, **{"$ai_evaluation_result": True})
        flush_persons_and_events()
        now = datetime(2026, 3, 10, 12, 30, tzinfo=UTC)

        overview = get_evaluations_overview(
            self.team, None, [str(judge.id)], PeriodBounds(start=now - timedelta(hours=24), end=now)
        )

        [row] = overview.evaluations
        assert overview.interval == "hour"
        assert overview.buckets[0] == datetime(2026, 3, 9, 12, tzinfo=UTC)
        assert len(overview.buckets) == 25
        assert (overview.previous_start, overview.previous_end) == (
            now - timedelta(hours=48),
            now - timedelta(hours=24),
        )
        assert row.trend.volume[:2] == [1, 2]
        assert row.trend.volume[-1] == 1
        assert sum(row.trend.volume) == 4
        assert row.previous_graded_count == 2
