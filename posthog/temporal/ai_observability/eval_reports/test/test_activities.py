import datetime as dt
from contextlib import asynccontextmanager

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import MagicMock, Mock, patch

from django.utils import timezone

from posthog.models import Team
from posthog.temporal.ai_observability.eval_reports import activities
from posthog.temporal.ai_observability.eval_reports.activities import (
    _check_count_triggered_eval_report_sync,
    _check_count_triggered_eval_reports_batch,
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

    def test_batch_skips_gated_reports_without_clickhouse_and_preserves_order(self):
        # Every Postgres-gated report must be resolved without touching ClickHouse — that's
        # the whole point of the batched path (stop firing count queries for reports we'll skip).
        now = timezone.now()
        not_deliverable = self._create_report(enabled=False)
        cooldown = self._create_report(last_delivered_at=now - dt.timedelta(minutes=5), cooldown_minutes=60)
        daily_cap = self._create_report(daily_run_cap=1)
        EvaluationReportRun.objects.create(
            report=daily_cap,
            period_start=now - dt.timedelta(hours=1),
            period_end=now,
        )

        report_ids = [str(not_deliverable.id), str(cooldown.id), str(daily_cap.id)]
        with patch("posthog.hogql.query.execute_hogql_query") as execute_hogql_query:
            results = _check_count_triggered_eval_reports_batch(report_ids, now)

        execute_hogql_query.assert_not_called()
        self.assertEqual([r.report_id for r in results], report_ids)
        self.assertEqual([r.skipped_reason for r in results], ["not_deliverable", "cooldown", "daily_cap"])
        self.assertTrue(all(r.due is False for r in results))


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


class TestBatchedCountTriggeredQuery(ClickhouseTestMixin, BaseTest):
    """Exercises the batched count check against real ClickHouse events — no query mocking —
    so it guards the properties Carlos cares about: each report's count is identical to the
    single-report query (right evaluation, right `since` window, right threshold)."""

    # Window anchor; reports use this as `since` (via last_delivered_at) unless overridden.
    T0 = dt.datetime(2026, 6, 1, 9, 0, tzinfo=dt.UTC)
    NOW = dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.UTC)

    def _create_report(self, team: Team, *, threshold: int, since: dt.datetime, name: str) -> EvaluationReport:
        evaluation = Evaluation.objects.create(
            team=team,
            name=name,
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            conditions=[{"id": "c1", "rollout_percentage": 100, "properties": []}],
        )
        return EvaluationReport.objects.create(
            team=team,
            evaluation=evaluation,
            frequency=EvaluationReport.Frequency.EVERY_N,
            rrule="",
            starts_at=None,
            trigger_threshold=threshold,
            # since = last_delivered_at; cooldown default is 60min and NOW is 3h later, so it passes.
            last_delivered_at=since,
            delivery_targets=[{"type": "email", "value": "test@example.com"}],
        )

    def _emit_eval_events(self, team: Team, evaluation_id: str, timestamps: list[dt.datetime]) -> None:
        for index, ts in enumerate(timestamps):
            _create_event(
                team=team,
                event="$ai_evaluation",
                distinct_id=f"d-{evaluation_id}-{index}",
                timestamp=ts,
                properties={"$ai_evaluation_id": evaluation_id},
            )

    def test_counts_respect_since_evaluation_and_threshold(self):
        # A: 2 events in-window (threshold 2) -> due. One event before `since` must be excluded.
        report_a = self._create_report(self.team, threshold=2, since=self.T0, name="A")
        self._emit_eval_events(
            self.team,
            str(report_a.evaluation_id),
            [self.T0 - dt.timedelta(hours=1), self.T0 + dt.timedelta(hours=1), self.T0 + dt.timedelta(hours=2)],
        )
        # B: same window as A but threshold 5 with only 2 events -> not due. Guards against
        # B's count picking up A's events (evaluation isolation).
        report_b = self._create_report(self.team, threshold=5, since=self.T0, name="B")
        self._emit_eval_events(
            self.team,
            str(report_b.evaluation_id),
            [self.T0 + dt.timedelta(hours=1), self.T0 + dt.timedelta(hours=2)],
        )
        # C: later `since` (11:00) than A/B — its only event (10:00) predates its window, so 0 -> not due.
        # This proves each report applies its OWN since, not a shared one.
        report_c = self._create_report(self.team, threshold=1, since=self.T0 + dt.timedelta(hours=2), name="C")
        self._emit_eval_events(self.team, str(report_c.evaluation_id), [self.T0 + dt.timedelta(hours=1)])

        report_ids = [str(report_a.id), str(report_b.id), str(report_c.id)]
        results = _check_count_triggered_eval_reports_batch(report_ids, self.NOW)

        due_by_id = {r.report_id: r.due for r in results}
        self.assertEqual([r.report_id for r in results], report_ids)
        self.assertTrue(due_by_id[str(report_a.id)])
        self.assertFalse(due_by_id[str(report_b.id)])
        self.assertFalse(due_by_id[str(report_c.id)])

    def test_counts_are_scoped_per_team(self):
        # One report per team, each with a single in-window event and threshold 1. If the batch
        # ran both against one team's data, the other team's report would count 0 and be not-due.
        report_a = self._create_report(self.team, threshold=1, since=self.T0, name="team1")
        self._emit_eval_events(self.team, str(report_a.evaluation_id), [self.T0 + dt.timedelta(hours=1)])

        other_team = Team.objects.create(organization=self.organization, name="other")
        report_b = self._create_report(other_team, threshold=1, since=self.T0, name="team2")
        self._emit_eval_events(other_team, str(report_b.evaluation_id), [self.T0 + dt.timedelta(hours=1)])

        results = _check_count_triggered_eval_reports_batch([str(report_a.id), str(report_b.id)], self.NOW)

        due_by_id = {r.report_id: r.due for r in results}
        self.assertTrue(due_by_id[str(report_a.id)])
        self.assertTrue(due_by_id[str(report_b.id)])

    def test_width_chunking_returns_all_counts(self):
        # Force one countIf column per query so the per-team entries span multiple chunks;
        # a chunk-merge bug (dropped/overwritten counts) would leave some report not-due.
        reports = [self._create_report(self.team, threshold=1, since=self.T0, name=f"r{i}") for i in range(3)]
        for report in reports:
            self._emit_eval_events(self.team, str(report.evaluation_id), [self.T0 + dt.timedelta(hours=1)])

        report_ids = [str(report.id) for report in reports]
        with patch("posthog.temporal.ai_observability.eval_reports.activities.COUNT_TRIGGER_QUERY_WIDTH", 1):
            results = _check_count_triggered_eval_reports_batch(report_ids, self.NOW)

        self.assertEqual([r.report_id for r in results], report_ids)
        self.assertTrue(all(r.due for r in results))

    def test_one_teams_query_failure_is_isolated_from_other_teams(self):
        # A healthy team (one in-window event, threshold 1 -> due) alongside a team whose count
        # query raises. Without per-team isolation the exception fails the whole batch and
        # discards the healthy team's already-computed result; with it, the blast radius is the
        # failing team only — it comes back skipped, the healthy team still resolves due.
        healthy = self._create_report(self.team, threshold=1, since=self.T0, name="healthy")
        self._emit_eval_events(self.team, str(healthy.evaluation_id), [self.T0 + dt.timedelta(hours=1)])

        failing_team = Team.objects.create(organization=self.organization, name="failing")
        failing = self._create_report(failing_team, threshold=1, since=self.T0, name="failing")
        self._emit_eval_events(failing_team, str(failing.evaluation_id), [self.T0 + dt.timedelta(hours=1)])

        real_count = activities._count_eval_results_for_reports

        def flaky(team, entries):
            if team.pk == failing_team.pk:
                raise Exception("ClickHouseAtCapacity: too many simultaneous queries")
            return real_count(team, entries)

        report_ids = [str(healthy.id), str(failing.id)]
        with patch.object(activities, "_count_eval_results_for_reports", side_effect=flaky):
            results = _check_count_triggered_eval_reports_batch(report_ids, self.NOW)

        by_id = {r.report_id: r for r in results}
        self.assertEqual([r.report_id for r in results], report_ids)
        self.assertTrue(by_id[str(healthy.id)].due)
        self.assertIsNone(by_id[str(healthy.id)].skipped_reason)
        self.assertFalse(by_id[str(failing.id)].due)
        self.assertEqual(by_id[str(failing.id)].skipped_reason, "count_query_error")

    def test_since_boundary_respects_non_utc_team_timezone(self):
        # `since` is passed as an ast.Constant datetime so ClickHouse compares the same absolute
        # instant whatever the team's timezone. If it were serialized as a bare string it would be
        # read in the team's tz (America/New_York, -4h in June) and shift the boundary. Events sit
        # an hour either side of `since`, so the ~4h shift a string would cause flips the result.
        ny_team = Team.objects.create(organization=self.organization, name="ny", timezone="America/New_York")
        report = self._create_report(ny_team, threshold=1, since=self.NOW, name="ny")
        self._emit_eval_events(
            ny_team,
            str(report.evaluation_id),
            [self.NOW - dt.timedelta(hours=1), self.NOW + dt.timedelta(hours=1)],
        )

        results = _check_count_triggered_eval_reports_batch([str(report.id)], self.NOW + dt.timedelta(hours=2))

        # Only the event after `since` is counted: exactly 1, meeting the threshold of 1.
        self.assertTrue(results[0].due)
