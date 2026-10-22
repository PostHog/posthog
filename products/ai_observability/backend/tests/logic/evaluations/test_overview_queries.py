from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from products.ai_observability.backend.facade.api import (
    get_evaluation_pass_filters,
    get_evaluations_overview,
    period_bound,
)
from products.ai_observability.backend.logic.evaluations.overview_queries import (
    CategoryBucketCount,
    load_bucket_counts,
    load_category_counts,
)
from products.ai_observability.backend.logic.evaluations.period import OverviewPeriod, overview_period
from products.ai_observability.backend.models.evaluations import Evaluation

PERIOD = OverviewPeriod(
    start=datetime(2026, 3, 8, tzinfo=UTC),
    end=datetime(2026, 3, 15, tzinfo=UTC),
    previous_start=datetime(2026, 3, 1, tzinfo=UTC),
    previous_end=datetime(2026, 3, 8, tzinfo=UTC),
    interval="day",
    buckets=(),
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

    @parameterized.expand([("one page", 50_000), ("several pages", 2)])
    def test_groups_runs_by_evaluation_day_and_period(self, _name: str, page_size: int) -> None:
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
        with patch("products.ai_observability.backend.logic.evaluations.overview_queries.PAGE_SIZE", page_size):
            bucket_counts = load_bucket_counts(self.team, None, PERIOD, ids, get_evaluation_pass_filters(self.team.pk))
            category_counts = load_category_counts(self.team, None, PERIOD, [str(topic.id)])
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
            period_bound(self.team, date(2026, 3, 9), is_end=False),
            period_bound(self.team, date(2026, 3, 10), is_end=True),
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
            period_bound(self.team, date(2026, 3, 8), is_end=False),
            period_bound(self.team, date(2026, 3, 11), is_end=True),
        )

        [row] = overview.evaluations
        assert overview.interval == "day"
        assert row.trend.volume == [0, 1, 0, 0]

    @time_machine.travel(datetime(2026, 11, 1, 18, 0, tzinfo=UTC), tick=False)
    def test_runs_in_a_repeated_daylight_saving_hour_land_in_their_own_buckets(self) -> None:
        self.team.timezone = "America/New_York"
        self.team.save()
        judge = self._judge()
        # 01:30 on November 1 in New York, before and after the clocks fall back.
        for timestamp in ("2026-11-01T05:30:00Z", "2026-11-01T06:30:00Z"):
            self._run(judge, timestamp, **{"$ai_evaluation_result": True})
        flush_persons_and_events()
        now = datetime(2026, 11, 1, 18, 0, tzinfo=UTC)

        overview = get_evaluations_overview(self.team, None, [str(judge.id)], now - timedelta(hours=24), now)

        [row] = overview.evaluations
        first_hour = [bucket.astimezone(UTC) for bucket in overview.buckets].index(datetime(2026, 11, 1, 5, tzinfo=UTC))
        assert row.trend.volume[first_hour : first_hour + 2] == [1, 1]
        assert sum(row.trend.volume) == row.graded_count == 2

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

        overview = get_evaluations_overview(self.team, None, [str(judge.id)], now - timedelta(hours=24), now)

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
