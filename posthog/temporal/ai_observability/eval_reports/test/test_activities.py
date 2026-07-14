import datetime as dt
from contextlib import asynccontextmanager

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, Mock, patch

from django.utils import timezone

from posthog.temporal.ai_observability.eval_reports.activities import (
    _check_count_triggered_eval_report_sync,
    _count_eval_results_for_report,
    _fetch_count_triggered_eval_report_candidate_ids,
    _find_nth_eval_timestamp,
    _period_for_scheduled_report,
    run_eval_report_agent_activity,
    store_report_run_activity,
)
from posthog.temporal.ai_observability.eval_reports.report_agent.schema import EvalReportContent, EvalReportMetrics
from posthog.temporal.ai_observability.eval_reports.types import RunEvalReportAgentInput, StoreReportRunInput

from products.ai_observability.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun
from products.ai_observability.backend.models.evaluations import Evaluation


@pytest.mark.asyncio
async def test_run_agent_activity_forwards_sentiment_output_type() -> None:
    @asynccontextmanager
    async def noop_heartbeater():
        yield

    content = EvalReportContent(metrics=EvalReportMetrics(output_type="sentiment"))
    inputs = RunEvalReportAgentInput(
        report_id="report-id",
        team_id=1,
        evaluation_id="evaluation-id",
        evaluation_name="Sentiment",
        evaluation_description="",
        evaluation_prompt="",
        evaluation_type="sentiment",
        output_type="sentiment",
        period_start="2026-07-01T00:00:00+00:00",
        period_end="2026-07-02T00:00:00+00:00",
        previous_period_start="2026-06-30T00:00:00+00:00",
    )

    with (
        patch(
            "posthog.temporal.ai_observability.eval_reports.activities.Heartbeater",
            return_value=noop_heartbeater(),
        ),
        patch(
            "posthog.temporal.ai_observability.eval_reports.report_agent.run_eval_report_agent",
            return_value=content,
        ) as run_agent,
    ):
        result = await run_eval_report_agent_activity(inputs)

    assert result.content["metrics"]["output_type"] == "sentiment"
    assert run_agent.call_args.kwargs["output_type"] == "sentiment"


@pytest.mark.asyncio
async def test_store_sentiment_report_emits_generic_metrics_only() -> None:
    report_run = MagicMock(id="run-id", report_id="report-id")
    expected_result_counts = {"positive": 2, "neutral": 3, "negative": 5}
    content = {
        "title": "Sentiment shifted negative",
        "sections": [],
        "citations": [],
        "metrics": {
            "output_type": "sentiment",
            "total_runs": 10,
            "result_counts": expected_result_counts,
            "result_rates": {"positive": 20.0, "neutral": 30.0, "negative": 50.0},
        },
    }
    inputs = StoreReportRunInput(
        report_id="report-id",
        team_id=1,
        evaluation_id="evaluation-id",
        content=content,
        period_start="2026-07-01T00:00:00+00:00",
        period_end="2026-07-02T00:00:00+00:00",
    )

    with (
        patch(
            "products.ai_observability.backend.models.evaluation_reports.EvaluationReportRun.objects.create",
            return_value=report_run,
        ),
        patch("posthog.models.team.Team.objects.get", return_value=MagicMock()),
        patch("posthog.models.event.util.create_event") as create_event,
    ):
        result = await store_report_run_activity(inputs)

    properties = create_event.call_args.kwargs["properties"]
    assert result.report_run_id == "run-id"
    assert properties["$ai_report_output_type"] == "sentiment"
    assert properties["$ai_report_result_counts"] == expected_result_counts
    assert "$ai_report_pass_rate" not in properties


@pytest.mark.asyncio
async def test_store_legacy_boolean_report_emits_normalized_generic_metrics() -> None:
    report_run = MagicMock(id="run-id", report_id="report-id")
    content = {
        "metrics": {
            "total_runs": 10,
            "pass_count": 6,
            "fail_count": 3,
            "na_count": 1,
            "pass_rate": 66.67,
        }
    }
    inputs = StoreReportRunInput(
        report_id="report-id",
        team_id=1,
        evaluation_id="evaluation-id",
        content=content,
        period_start="2026-07-01T00:00:00+00:00",
        period_end="2026-07-02T00:00:00+00:00",
    )

    with (
        patch(
            "products.ai_observability.backend.models.evaluation_reports.EvaluationReportRun.objects.create",
            return_value=report_run,
        ) as create_report_run,
        patch("posthog.models.team.Team.objects.get", return_value=MagicMock()),
        patch("posthog.models.event.util.create_event") as create_event,
    ):
        await store_report_run_activity(inputs)

    properties = create_event.call_args.kwargs["properties"]
    stored_content = create_report_run.call_args.kwargs["content"]
    stored_metrics = stored_content["metrics"]
    assert stored_metrics["result_counts"] == {"pass": 6, "fail": 3, "na": 1}
    assert create_report_run.call_args.kwargs["metadata"] == stored_metrics
    assert "pass_count" not in stored_metrics
    assert "fail_count" not in stored_metrics
    assert "na_count" not in stored_metrics
    assert properties["$ai_report_output_type"] == "boolean"
    assert properties["$ai_report_result_counts"] == {"pass": 6, "fail": 3, "na": 1}
    assert properties["$ai_report_result_rates"] == {"pass": 60.0, "fail": 30.0, "na": 10.0}
    assert properties["$ai_report_pass_rate"] == 66.67


def test_count_trigger_uses_current_output_type() -> None:
    report = MagicMock(team_id=1, team=MagicMock(), evaluation_id="evaluation-id")
    report.evaluation.output_type = "sentiment"

    with (
        patch("posthog.hogql.parser.parse_select", return_value=MagicMock()) as parse_select,
        patch("posthog.hogql.query.execute_hogql_query", return_value=Mock(results=[[4]])),
    ):
        result = _count_eval_results_for_report(report, dt.datetime(2026, 7, 1, tzinfo=dt.UTC))

    assert result == 4
    assert "properties.$ai_evaluation_result_type = 'sentiment'" in parse_select.call_args.args[0]


def test_manual_count_window_uses_current_output_type() -> None:
    before = dt.datetime(2026, 7, 2, tzinfo=dt.UTC)
    expected = before - dt.timedelta(hours=2)

    with (
        patch("posthog.hogql.parser.parse_select", return_value=MagicMock()) as parse_select,
        patch("posthog.hogql.query.execute_hogql_query", return_value=Mock(results=[[expected]])),
        patch("posthog.models.Team.objects.get", return_value=MagicMock()),
    ):
        result = _find_nth_eval_timestamp(1, "evaluation-id", 100, before, output_type="sentiment")

    assert result == expected
    assert "properties.$ai_evaluation_result_type = 'sentiment'" in parse_select.call_args.args[0]


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


class TestCountTriggeredReportChecks(BaseTest):
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
            "frequency": EvaluationReport.Frequency.EVERY_N,
            "rrule": "",
            "starts_at": None,
            "trigger_threshold": 100,
            "delivery_targets": [{"type": "email", "value": "test@example.com"}],
        }
        defaults.update(kwargs)
        return EvaluationReport.objects.create(**defaults)

    def test_fetch_candidates_returns_only_deliverable_count_triggered_reports(self):
        count_triggered_report = self._create_report()
        self._create_report(enabled=False)
        self._create_report(
            frequency=EvaluationReport.Frequency.SCHEDULED,
            rrule="FREQ=HOURLY",
            starts_at=timezone.now() - dt.timedelta(hours=5),
        )

        with patch("posthog.hogql.query.execute_hogql_query") as execute_hogql_query:
            report_ids = _fetch_count_triggered_eval_report_candidate_ids()

        self.assertEqual(report_ids, [str(count_triggered_report.id)])
        execute_hogql_query.assert_not_called()

    def test_check_report_returns_due_when_threshold_is_crossed(self):
        report = self._create_report(trigger_threshold=100)

        with patch("posthog.hogql.query.execute_hogql_query") as execute_hogql_query:
            execute_hogql_query.return_value = Mock(results=[[100]])
            result = _check_count_triggered_eval_report_sync(str(report.id), timezone.now())

        self.assertTrue(result.due)
        self.assertIsNone(result.skipped_reason)
        execute_hogql_query.assert_called_once()

    def test_check_report_skips_cooldown_without_clickhouse_query(self):
        now = timezone.now()
        report = self._create_report(
            last_delivered_at=now - dt.timedelta(minutes=5),
            cooldown_minutes=60,
        )

        with patch("posthog.hogql.query.execute_hogql_query") as execute_hogql_query:
            result = _check_count_triggered_eval_report_sync(str(report.id), now)

        self.assertFalse(result.due)
        self.assertEqual(result.skipped_reason, "cooldown")
        execute_hogql_query.assert_not_called()

    def test_check_report_skips_daily_cap_without_clickhouse_query(self):
        now = timezone.now()
        report = self._create_report(daily_run_cap=1)
        EvaluationReportRun.objects.create(
            report=report,
            period_start=now - dt.timedelta(hours=1),
            period_end=now,
        )

        with patch("posthog.hogql.query.execute_hogql_query") as execute_hogql_query:
            result = _check_count_triggered_eval_report_sync(str(report.id), now)

        self.assertFalse(result.due)
        self.assertEqual(result.skipped_reason, "daily_cap")
        execute_hogql_query.assert_not_called()


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
