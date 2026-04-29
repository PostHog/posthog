import datetime as dt

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.temporal.llm_analytics.eval_reports.activities import _period_for_scheduled_report

from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport
from products.llm_analytics.backend.models.evaluations import Evaluation


def _prepare_sync(report_id: str, manual: bool = False):
    """Call the inner sync logic of prepare_report_context_activity directly.

    Mirrors the real activity's period computation so we can assert on time windows
    without spinning up Temporal.
    """
    report = EvaluationReport.objects.select_related("evaluation").get(id=report_id)
    evaluation = report.evaluation
    now = dt.datetime.now(tz=dt.UTC)

    period_end = now

    if manual:
        if report.is_count_triggered:
            # Count-triggered manual runs look back to `starts_at or created_at`
            # in this test helper — the real activity uses _find_nth_eval_timestamp
            # which requires ClickHouse.
            period_start = report.starts_at or report.created_at
        else:
            period_start = now - _period_for_scheduled_report(report, now)
    elif report.last_delivered_at:
        period_start = report.last_delivered_at
    elif report.is_count_triggered:
        period_start = report.starts_at or report.created_at
    else:
        period_start = now - _period_for_scheduled_report(report, now)

    period_duration = period_end - period_start
    previous_period_start = period_start - period_duration

    return {
        "report_id": str(report.id),
        "team_id": report.team_id,
        "evaluation_id": str(evaluation.id),
        "evaluation_name": evaluation.name,
        "period_start": period_start,
        "period_end": period_end,
        "previous_period_start": previous_period_start,
        "manual": manual,
    }


class TestPrepareReportContext(BaseTest):
    def _create_report(self, **kwargs) -> EvaluationReport:
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Eval",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "c1", "rollout_percentage": 100, "properties": []}],
        )
        defaults = {
            "team": self.team,
            "evaluation": evaluation,
            "frequency": EvaluationReport.Frequency.SCHEDULED,
            "rrule": "FREQ=HOURLY",
            "starts_at": timezone.now() - dt.timedelta(hours=5),
            "delivery_targets": [{"type": "email", "value": "test@example.com"}],
        }
        defaults.update(kwargs)
        return EvaluationReport.objects.create(**defaults)

    def test_manual_scheduled_uses_rrule_period(self):
        report = self._create_report(rrule="FREQ=HOURLY")
        result = _prepare_sync(str(report.id), manual=True)
        duration = result["period_end"] - result["period_start"]
        self.assertAlmostEqual(duration.total_seconds(), 3600, delta=5)

    def test_manual_daily_rrule_uses_full_day_lookback(self):
        report = self._create_report(rrule="FREQ=DAILY")
        result = _prepare_sync(str(report.id), manual=True)
        duration = result["period_end"] - result["period_start"]
        self.assertAlmostEqual(duration.total_seconds(), 86400, delta=5)

    def test_manual_weekly_rrule_uses_full_week_lookback(self):
        now = timezone.now()
        # Two+ prior occurrences are needed for _period_for_scheduled_report to
        # measure the gap; anchor well in the past.
        report = self._create_report(rrule="FREQ=WEEKLY", starts_at=now - dt.timedelta(weeks=3))
        result = _prepare_sync(str(report.id), manual=True)
        duration = result["period_end"] - result["period_start"]
        self.assertAlmostEqual(duration.total_seconds(), 7 * 86400, delta=5)

    def test_scheduled_first_run_uses_rrule_period(self):
        report = self._create_report(rrule="FREQ=HOURLY")
        result = _prepare_sync(str(report.id), manual=False)
        duration = result["period_end"] - result["period_start"]
        self.assertAlmostEqual(duration.total_seconds(), 3600, delta=5)

    def test_scheduled_run_uses_last_delivered_at(self):
        last_delivered = dt.datetime.now(tz=dt.UTC) - dt.timedelta(minutes=30)
        report = self._create_report(rrule="FREQ=HOURLY", last_delivered_at=last_delivered)
        result = _prepare_sync(str(report.id), manual=False)
        self.assertEqual(result["period_start"], last_delivered)

    def test_count_triggered_first_run_uses_starts_at_or_created_at(self):
        # Count-triggered reports don't have a time-based period; fall back to
        # starts_at (if set) or created_at so there's always a usable anchor.
        report = self._create_report(
            frequency=EvaluationReport.Frequency.EVERY_N,
            rrule="",
            starts_at=None,
            trigger_threshold=100,
        )
        result = _prepare_sync(str(report.id), manual=False)
        # created_at is the anchor when starts_at is None
        self.assertEqual(result["period_start"], report.created_at)

    def test_previous_period_calculation(self):
        report = self._create_report(rrule="FREQ=HOURLY")
        result = _prepare_sync(str(report.id), manual=True)
        period_duration = result["period_end"] - result["period_start"]
        expected_prev = result["period_start"] - period_duration
        self.assertEqual(result["previous_period_start"], expected_prev)

    def test_manual_run_ignores_last_delivered_at(self):
        last_delivered = dt.datetime.now(tz=dt.UTC) - dt.timedelta(minutes=15)
        report = self._create_report(rrule="FREQ=HOURLY", last_delivered_at=last_delivered)
        result = _prepare_sync(str(report.id), manual=True)
        duration = result["period_end"] - result["period_start"]
        self.assertAlmostEqual(duration.total_seconds(), 3600, delta=5)

    def test_context_includes_evaluation_metadata(self):
        report = self._create_report()
        result = _prepare_sync(str(report.id))
        self.assertEqual(result["evaluation_name"], "Test Eval")
        self.assertEqual(result["team_id"], self.team.id)


class TestPeriodForScheduledReport(BaseTest):
    """Unit-ish tests for the rrule period helper — uses in-memory instances to
    bypass model save validation so we can exercise fallback paths."""

    def _make(self, rrule_str: str, starts_at_offset_weeks: int = 3) -> EvaluationReport:
        return EvaluationReport(
            team=self.team,
            frequency=EvaluationReport.Frequency.SCHEDULED,
            rrule=rrule_str,
            starts_at=timezone.now() - dt.timedelta(weeks=starts_at_offset_weeks),
        )

    def test_hourly_rrule(self):
        report = self._make("FREQ=HOURLY")
        period = _period_for_scheduled_report(report, dt.datetime.now(tz=dt.UTC))
        self.assertAlmostEqual(period.total_seconds(), 3600, delta=1)

    def test_daily_rrule(self):
        report = self._make("FREQ=DAILY")
        period = _period_for_scheduled_report(report, dt.datetime.now(tz=dt.UTC))
        self.assertAlmostEqual(period.total_seconds(), 86400, delta=1)

    def test_weekly_rrule(self):
        report = self._make("FREQ=WEEKLY")
        period = _period_for_scheduled_report(report, dt.datetime.now(tz=dt.UTC))
        self.assertAlmostEqual(period.total_seconds(), 7 * 86400, delta=1)

    def test_fallback_when_empty_rrule(self):
        report = self._make("")
        period = _period_for_scheduled_report(report, dt.datetime.now(tz=dt.UTC))
        self.assertEqual(period, dt.timedelta(days=1))

    def test_fallback_when_malformed_rrule(self):
        report = self._make("NOT_A_RRULE")
        period = _period_for_scheduled_report(report, dt.datetime.now(tz=dt.UTC))
        self.assertEqual(period, dt.timedelta(days=1))

    def test_daily_rrule_reports_23h_gap_across_dst_spring_forward(self):
        # America/New_York springs forward at 2026-03-08 02:00 local.
        # 09:00 EST on 2026-03-07 == 14:00 UTC; 09:00 EDT on 2026-03-08 == 13:00 UTC.
        # The real wall-clock gap between consecutive "9am local" fires is 23h.
        # A tz-naive rrulestr(..., dtstart=starts_at).before() would report 24h.
        report = EvaluationReport(
            team=self.team,
            frequency=EvaluationReport.Frequency.SCHEDULED,
            rrule="FREQ=DAILY;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
            starts_at=dt.datetime(2026, 3, 1, 14, 0, tzinfo=dt.UTC),  # 9am EST
            timezone_name="America/New_York",
        )
        # `now` sits after the transition so prev/prev_prev straddle it.
        now = dt.datetime(2026, 3, 8, 18, 0, tzinfo=dt.UTC)  # 14:00 EDT, after 9am EDT fire
        period = _period_for_scheduled_report(report, now)
        self.assertEqual(period, dt.timedelta(hours=23))
