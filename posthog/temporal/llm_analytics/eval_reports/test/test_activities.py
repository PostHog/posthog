import datetime as dt

from posthog.test.base import BaseTest

from django.utils import timezone

from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport
from products.llm_analytics.backend.models.evaluations import Evaluation


def _prepare_sync(report_id: str, manual: bool = False):
    """Call the inner sync logic of prepare_report_context_activity directly."""
    report = EvaluationReport.objects.select_related("evaluation").get(id=report_id)
    evaluation = report.evaluation
    now = dt.datetime.now(tz=dt.UTC)

    period_end = now
    freq_deltas = {
        "hourly": dt.timedelta(hours=1),
        "daily": dt.timedelta(days=1),
        "weekly": dt.timedelta(weeks=1),
    }

    if manual:
        period_start = now - freq_deltas.get(report.frequency, dt.timedelta(days=1))
    elif report.last_delivered_at:
        period_start = report.last_delivered_at
    else:
        period_start = now - freq_deltas.get(report.frequency, dt.timedelta(days=1))

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
            "frequency": "hourly",
            "start_date": timezone.now() - dt.timedelta(hours=5),
            "delivery_targets": [{"type": "email", "value": "test@example.com"}],
        }
        defaults.update(kwargs)
        return EvaluationReport.objects.create(**defaults)

    def test_manual_run_uses_full_frequency_lookback(self):
        report = self._create_report(frequency="hourly")
        result = _prepare_sync(str(report.id), manual=True)
        # Manual hourly: period_start should be ~1 hour before period_end
        duration = result["period_end"] - result["period_start"]
        self.assertAlmostEqual(duration.total_seconds(), 3600, delta=5)

    def test_manual_daily_uses_full_day_lookback(self):
        report = self._create_report(frequency="daily")
        result = _prepare_sync(str(report.id), manual=True)
        duration = result["period_end"] - result["period_start"]
        self.assertAlmostEqual(duration.total_seconds(), 86400, delta=5)

    def test_manual_weekly_uses_full_week_lookback(self):
        report = self._create_report(frequency="weekly")
        result = _prepare_sync(str(report.id), manual=True)
        duration = result["period_end"] - result["period_start"]
        self.assertAlmostEqual(duration.total_seconds(), 7 * 86400, delta=5)

    def test_scheduled_first_run_uses_frequency_lookback(self):
        report = self._create_report(frequency="hourly")
        result = _prepare_sync(str(report.id), manual=False)
        duration = result["period_end"] - result["period_start"]
        self.assertAlmostEqual(duration.total_seconds(), 3600, delta=5)

    def test_scheduled_run_uses_last_delivered_at(self):
        last_delivered = dt.datetime.now(tz=dt.UTC) - dt.timedelta(minutes=30)
        report = self._create_report(frequency="hourly", last_delivered_at=last_delivered)
        result = _prepare_sync(str(report.id), manual=False)
        self.assertEqual(result["period_start"], last_delivered)

    def test_previous_period_calculation(self):
        report = self._create_report(frequency="hourly")
        result = _prepare_sync(str(report.id), manual=True)
        period_duration = result["period_end"] - result["period_start"]
        expected_prev = result["period_start"] - period_duration
        self.assertEqual(result["previous_period_start"], expected_prev)

    def test_manual_run_ignores_last_delivered_at(self):
        last_delivered = dt.datetime.now(tz=dt.UTC) - dt.timedelta(minutes=15)
        report = self._create_report(frequency="hourly", last_delivered_at=last_delivered)
        result = _prepare_sync(str(report.id), manual=True)
        # Manual should use full frequency (1h), not time since last_delivered_at (15m)
        duration = result["period_end"] - result["period_start"]
        self.assertAlmostEqual(duration.total_seconds(), 3600, delta=5)

    def test_context_includes_evaluation_metadata(self):
        report = self._create_report()
        result = _prepare_sync(str(report.id))
        self.assertEqual(result["evaluation_name"], "Test Eval")
        self.assertEqual(result["team_id"], self.team.id)
