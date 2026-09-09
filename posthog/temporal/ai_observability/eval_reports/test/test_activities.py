import datetime as dt
from contextlib import asynccontextmanager

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import MagicMock, Mock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from asgiref.sync import sync_to_async
from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import TraversingVisitor

from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models import Team
from posthog.temporal.ai_observability.eval_reports.activities import (
    _check_count_triggered_eval_report_sync,
    _check_count_triggered_eval_reports_batch,
    _count_eval_results_for_report,
    _count_eval_results_for_reports_with_split_retry,
    _CountEntry,
    _fetch_count_triggered_eval_report_candidate_groups,
    _find_nth_eval_timestamp,
    _load_detector_evaluation_ids,
    _load_evaluation_target,
    _period_for_scheduled_report,
    _update_next_delivery_date,
    prepare_report_context_activity,
    run_eval_report_agent_activity,
    store_report_run_activity,
)
from posthog.temporal.ai_observability.eval_reports.constants import (
    COUNT_TRIGGER_MAX_LOOKBACK,
    COUNT_TRIGGER_QUERY_MAX_EXECUTION_TIME_SECONDS,
    COUNT_TRIGGER_QUERY_MIN_EXECUTION_TIME_SECONDS,
    COUNT_TRIGGER_QUERY_OVERSHOOT_FACTOR,
    COUNT_TRIGGER_QUERY_TOTAL_BUDGET_SECONDS,
)
from posthog.temporal.ai_observability.eval_reports.report_agent.schema import EvalReportContent, EvalReportMetrics
from posthog.temporal.ai_observability.eval_reports.targets import target_event_predicate
from posthog.temporal.ai_observability.eval_reports.types import (
    PrepareReportContextInput,
    RunEvalReportAgentInput,
    StoreReportRunInput,
    UpdateNextDeliveryDateInput,
)

from products.ai_observability.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun
from products.ai_observability.backend.models.evaluations import Evaluation


def _scanned_window(query: ast.SelectQuery) -> list[dt.datetime]:
    """Return the timestamp bounds a count query puts in its WHERE clause, oldest first.

    These bounds decide how many rows ClickHouse reads, which is what the lookback clamp and
    the time split control, so the tests assert on the query the code sends.
    """

    class CollectTimestamps(TraversingVisitor):
        def __init__(self) -> None:
            self.timestamps: list[dt.datetime] = []

        def visit_constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, dt.datetime):
                self.timestamps.append(node.value)

    visitor = CollectTimestamps()
    visitor.visit(query.where)
    return sorted(visitor.timestamps)


class TestUpdateNextDeliveryDate(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "unavailable_legacy",
                "metrics_unavailable",
                True,
                None,
                False,
                ["next_delivery_date", "last_attempted_at"],
            ),
            (
                "completed_legacy",
                "completed",
                True,
                None,
                True,
                ["next_delivery_date", "last_attempted_at", "last_delivered_at"],
            ),
            (
                "completed_cursor_only",
                "completed",
                False,
                True,
                True,
                ["last_delivered_at"],
            ),
        ]
    )
    @patch("products.ai_observability.backend.models.evaluation_reports.EvaluationReport.objects.get")
    def test_updates_automatic_report_timing(
        self,
        _name: str,
        generation_status: str,
        record_attempt: bool,
        advance_data_cursor: bool | None,
        expects_delivered_advance: bool,
        expected_update_fields: list[str],
        get_report: MagicMock,
    ) -> None:
        last_delivered = timezone.now() - dt.timedelta(hours=2)
        last_attempted = timezone.now() - dt.timedelta(hours=1)
        period_end = timezone.now()
        report = MagicMock(last_delivered_at=last_delivered, last_attempted_at=last_attempted)
        get_report.return_value = report

        _update_next_delivery_date(
            UpdateNextDeliveryDateInput(
                report_id="report-id",
                period_end=period_end.isoformat(),
                generation_status=generation_status,
                record_attempt=record_attempt,
                advance_data_cursor=advance_data_cursor,
            )
        )

        self.assertEqual(report.last_attempted_at, period_end if record_attempt else last_attempted)
        self.assertEqual(report.last_delivered_at, period_end if expects_delivered_advance else last_delivered)
        if record_attempt:
            report.set_next_delivery_date.assert_called_once_with()
        else:
            report.set_next_delivery_date.assert_not_called()
        report.save.assert_called_once_with(update_fields=expected_update_fields)


class TestEvaluationTargetLoading(BaseTest):
    def test_loads_target_without_deferred_model_fields(self) -> None:
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Trace evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "test prompt"},
            output_type="boolean",
            output_config={},
            target="trace",
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "c1", "rollout_percentage": 100, "properties": []}],
        )

        target = _load_evaluation_target(self.team.id, str(evaluation.id))

        self.assertEqual(target, "trace")

    def test_loads_only_the_team_evaluations_that_declare_true_a_failure(self) -> None:
        def _evaluation(name: str, output_config: dict) -> Evaluation:
            return Evaluation.objects.create(
                team=self.team,
                name=name,
                evaluation_type="llm_judge",
                evaluation_config={"prompt": "test prompt"},
                output_type="boolean",
                output_config=output_config,
                enabled=True,
                created_by=self.user,
                conditions=[{"id": "c1", "rollout_percentage": 100, "properties": []}],
            )

        detector = _evaluation("Detector", {"true_is_failure": True})
        _evaluation("Quality check", {"true_is_failure": False})
        _evaluation("Legacy config", {})

        self.assertEqual(_load_detector_evaluation_ids(self.team.id), [str(detector.id)])


@pytest.mark.parametrize(
    "target,expected",
    [
        ("session", "properties.$ai_target_type = 'session_id'"),
        ("trace", "properties.$ai_target_type = 'trace_id'"),
    ],
)
def test_target_event_predicate_per_target(target, expected):
    assert target_event_predicate(target) == expected


@pytest.mark.parametrize(
    ("output_type", "evaluation_target"),
    [("sentiment", "generation"), ("boolean", "trace")],
)
@pytest.mark.asyncio
async def test_run_agent_activity_loads_target_and_forwards_output_type(
    output_type: str, evaluation_target: str
) -> None:
    @asynccontextmanager
    async def noop_heartbeater():
        yield

    content = EvalReportContent(metrics=EvalReportMetrics(output_type=output_type))
    inputs = RunEvalReportAgentInput(
        report_id="report-id",
        team_id=1,
        evaluation_id="evaluation-id",
        evaluation_name="Sentiment",
        evaluation_description="",
        evaluation_prompt="",
        evaluation_type="sentiment",
        output_type=output_type,
        period_start="2026-07-01T00:00:00+00:00",
        period_end="2026-07-02T00:00:00+00:00",
        previous_period_start="2026-06-30T00:00:00+00:00",
        trace_id="report-run-id",
        session_id="report-session-id",
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
        patch(
            "posthog.temporal.ai_observability.eval_reports.activities._load_evaluation_target",
            return_value=evaluation_target,
        ) as load_target,
        patch(
            "posthog.temporal.ai_observability.eval_reports.activities._load_detector_evaluation_ids",
            return_value=["detector-id"],
        ) as load_detectors,
    ):
        result = await run_eval_report_agent_activity(inputs)

    assert result.content["metrics"]["output_type"] == output_type
    assert result.content["evaluation_target"] == evaluation_target
    assert result.generation_status == "completed"
    assert run_agent.call_args.args[0] is inputs
    assert run_agent.call_args.kwargs["evaluation_target"] == evaluation_target
    assert run_agent.call_args.kwargs["detector_evaluation_ids"] == ["detector-id"]
    load_target.assert_called_once_with(inputs.team_id, inputs.evaluation_id)
    load_detectors.assert_called_once_with(inputs.team_id)


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
        "citations": [
            {
                "generation_id": "generation-id",
                "trace_id": "customer/trace:42",
                "reason": "example",
            }
        ],
        "metrics": {
            "total_runs": 10,
            "pass_count": 6,
            "fail_count": 3,
            "na_count": 1,
            "pass_rate": 66.67,
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
    assert properties["$ai_report_evaluation_target"] == "generation"
    assert properties["$ai_report_referenced_generation_ids"] == ["generation-id"]
    assert properties["$ai_report_referenced_trace_ids"] == ["customer/trace:42"]


@pytest.mark.asyncio
async def test_store_metrics_unavailable_report_omits_placeholder_metrics() -> None:
    report_run = MagicMock(id="run-id", report_id="report-id")
    content: dict[str, object] = {
        "title": "Metrics temporarily unavailable",
        "sections": [],
        "citations": [],
        "generation_status": "metrics_unavailable",
        "metrics": None,
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
    assert create_report_run.call_args.kwargs["metadata"] == {}
    assert properties["$ai_report_generation_status"] == "metrics_unavailable"
    assert "$ai_report_total_runs" not in properties
    assert "$ai_report_result_counts" not in properties
    assert "$ai_report_pass_rate" not in properties


def test_count_trigger_uses_current_output_type() -> None:
    report = MagicMock(team_id=1, team=MagicMock(), evaluation_id="evaluation-id")
    report.evaluation.output_type = "sentiment"
    report.evaluation.target = "trace"

    with (
        patch("posthog.hogql.parser.parse_select", return_value=MagicMock()) as parse_select,
        patch("posthog.hogql.query.execute_hogql_query", return_value=Mock(results=[[4]])),
    ):
        result = _count_eval_results_for_report(report, dt.datetime(2026, 7, 1, tzinfo=dt.UTC))

    assert result == 4
    assert "properties.$ai_evaluation_result_type = 'sentiment'" in parse_select.call_args.args[0]
    assert "properties.$ai_target_type = 'trace_id'" in parse_select.call_args.args[0]


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
    assert "isNull(properties.$ai_target_type)" in parse_select.call_args.args[0]


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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_prepare_activity_reads_detector_polarity_from_evaluation(team, user) -> None:
    def _create_report() -> EvaluationReport:
        evaluation = Evaluation.objects.create(
            team=team,
            name="Detector Eval",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "test prompt"},
            output_type="boolean",
            output_config={"true_is_failure": True},
            enabled=True,
            created_by=user,
            conditions=[{"id": "c1", "rollout_percentage": 100, "properties": []}],
        )
        return EvaluationReport.objects.create(
            team=team,
            evaluation=evaluation,
            frequency=EvaluationReport.Frequency.SCHEDULED,
            rrule="FREQ=HOURLY",
            starts_at=timezone.now() - dt.timedelta(hours=5),
            delivery_targets=[{"type": "email", "value": "test@example.com"}],
        )

    report = await sync_to_async(_create_report)()

    context = await prepare_report_context_activity(PrepareReportContextInput(report_id=str(report.id)))

    assert context.true_is_failure is True


class TestCountTriggeredReportChecks(BaseTest):
    def _create_report(self, team: Team | None = None, **kwargs) -> EvaluationReport:
        team = team or self.team
        evaluation = Evaluation.objects.create(
            team=team,
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
            "team": team,
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
            groups = _fetch_count_triggered_eval_report_candidate_groups()

        self.assertEqual(groups, [[str(count_triggered_report.id)]])
        execute_hogql_query.assert_not_called()

    def test_fetch_candidates_groups_by_team_and_chunks_by_width(self):
        # One check activity handles one group, so a group must never span teams (its counts
        # would run against the wrong team's data) nor exceed the per-query width cap.
        team_a_report_ids = sorted(str(self._create_report().id) for _ in range(3))
        other_team = Team.objects.create(organization=self.organization, name="other")
        team_b_report = self._create_report(team=other_team)

        with patch("posthog.temporal.ai_observability.eval_reports.activities.COUNT_TRIGGER_QUERY_WIDTH", 2):
            groups = _fetch_count_triggered_eval_report_candidate_groups()

        self.assertEqual(groups, [team_a_report_ids[:2], team_a_report_ids[2:], [str(team_b_report.id)]])

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

    def test_check_report_uses_latest_attempt_for_cooldown_and_success_for_count_window(self):
        now = timezone.now()
        report = self._create_report(
            last_delivered_at=now - dt.timedelta(hours=2),
            last_attempted_at=now - dt.timedelta(minutes=5),
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

    def test_check_report_does_not_count_unavailable_run_toward_daily_cap(self):
        now = timezone.now()
        report = self._create_report(daily_run_cap=1)
        EvaluationReportRun.objects.create(
            report=report,
            content={"generation_status": "metrics_unavailable"},
            period_start=now - dt.timedelta(hours=1),
            period_end=now,
        )

        with patch("posthog.hogql.query.execute_hogql_query") as execute_hogql_query:
            execute_hogql_query.return_value = Mock(results=[[100]])
            result = _check_count_triggered_eval_report_sync(str(report.id), now)

        self.assertTrue(result.due)
        self.assertIsNone(result.skipped_reason)
        execute_hogql_query.assert_called_once()

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

    @parameterized.expand(
        [
            ("anchor_older_than_lookback", COUNT_TRIGGER_MAX_LOOKBACK * 12, COUNT_TRIGGER_MAX_LOOKBACK),
            ("anchor_inside_lookback", dt.timedelta(days=2), dt.timedelta(days=2)),
        ]
    )
    def test_count_window_never_reaches_further_back_than_the_lookback(self, _name, anchor_age, expected_age):
        # Catches a clamp that stops reaching the query, which returns the scan to unbounded.
        now = timezone.now()
        report = self._create_report(starts_at=now - anchor_age)

        with patch("posthog.hogql.query.execute_hogql_query") as execute_hogql_query:
            execute_hogql_query.return_value = Mock(results=[[1]])
            _check_count_triggered_eval_report_sync(str(report.id), now)

        self.assertEqual(_scanned_window(execute_hogql_query.call_args.kwargs["query"]), [now - expected_age])


class TestCountEvalResultsForReportsSplitRetry(BaseTest):
    """Guards the retry behavior a `ClickHouseQueryTimeOut` needs: halve the time range and
    retry over each half, rather than replaying a query over the same rows."""

    def _entries(self, count: int, since: dt.datetime) -> list[_CountEntry]:
        return [
            _CountEntry(
                key=f"r{i}",
                evaluation_id=f"e{i}",
                since=since,
                event_predicate="1 = 1",
                target_predicate="1 = 1",
            )
            for i in range(count)
        ]

    def test_splits_time_range_in_half_on_timeout_and_sums_the_halves(self):
        # Catches a retry that reads the same range again, as the old column split did.
        until = timezone.now()
        since = until - dt.timedelta(days=8)
        side_effects = [ClickHouseQueryTimeOut(), Mock(results=[[1, 2]]), Mock(results=[[30, 40]])]

        with patch("posthog.hogql.query.execute_hogql_query", side_effect=side_effects) as execute_hogql_query:
            counts = _count_eval_results_for_reports_with_split_retry(self.team, self._entries(2, since), until=until)

        self.assertEqual(counts, {"r0": 31, "r1": 42})
        midpoint = since + (until - since) / 2
        self.assertEqual(
            [_scanned_window(call.kwargs["query"]) for call in execute_hogql_query.call_args_list],
            [
                [since, until],
                [since, midpoint],
                [midpoint + dt.timedelta(microseconds=1), until],
            ],
        )

    def test_reraises_when_the_narrowest_range_still_times_out(self):
        # A range too narrow to halve has nothing cheaper to retry, so the failure must surface.
        until = timezone.now()
        with patch("posthog.hogql.query.execute_hogql_query", side_effect=ClickHouseQueryTimeOut()):
            with self.assertRaises(ClickHouseQueryTimeOut):
                _count_eval_results_for_reports_with_split_retry(
                    self.team, self._entries(1, until - dt.timedelta(seconds=30)), until=until
                )

    def test_stops_splitting_once_shared_budget_is_exhausted(self):
        # A first attempt that burns nearly the whole wall-clock budget must not be followed
        # by narrower retries: if each half drew a fresh budget instead of sharing the
        # deadline, the split tree could outlive the activity timeout again.
        clock = [0.0]
        until = timezone.now()

        def timeout_burning_budget(*args, **kwargs):
            clock[0] += COUNT_TRIGGER_QUERY_TOTAL_BUDGET_SECONDS - COUNT_TRIGGER_QUERY_MIN_EXECUTION_TIME_SECONDS + 1
            raise ClickHouseQueryTimeOut()

        with (
            patch("time.monotonic", side_effect=lambda: clock[0]),
            patch("posthog.hogql.query.execute_hogql_query", side_effect=timeout_burning_budget) as execute_hogql_query,
        ):
            with self.assertRaises(ClickHouseQueryTimeOut):
                _count_eval_results_for_reports_with_split_retry(
                    self.team, self._entries(4, until - dt.timedelta(days=8)), until=until
                )

        self.assertEqual(execute_hogql_query.call_count, 1)

    def test_execution_limit_leaves_room_for_clickhouse_to_overshoot_it(self):
        # Catches a retry that claims the whole remaining budget as its limit. ClickHouse can
        # run past that limit, so the attempt would overshoot the deadline and Temporal would
        # kill the split midway.
        clock = [0.0]
        until = timezone.now()
        remaining_after_first_attempt = COUNT_TRIGGER_QUERY_MAX_EXECUTION_TIME_SECONDS * 1.5
        execution_limits: list[int] = []

        def record_limit_then_time_out_once(*args, **kwargs):
            execution_limits.append(kwargs["settings"].max_execution_time)
            if len(execution_limits) > 1:
                return Mock(results=[[0]])
            clock[0] = COUNT_TRIGGER_QUERY_TOTAL_BUDGET_SECONDS - remaining_after_first_attempt
            raise ClickHouseQueryTimeOut()

        with (
            patch("time.monotonic", side_effect=lambda: clock[0]),
            patch("posthog.hogql.query.execute_hogql_query", side_effect=record_limit_then_time_out_once),
        ):
            _count_eval_results_for_reports_with_split_retry(
                self.team, self._entries(1, until - dt.timedelta(days=8)), until=until
            )

        self.assertEqual(execution_limits[0], COUNT_TRIGGER_QUERY_MAX_EXECUTION_TIME_SECONDS)
        self.assertEqual(execution_limits[1], int(remaining_after_first_attempt / COUNT_TRIGGER_QUERY_OVERSHOOT_FACTOR))


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

    def _create_report(
        self,
        team: Team,
        *,
        threshold: int,
        since: dt.datetime,
        name: str,
        output_type: str = "boolean",
        target: str = "generation",
    ) -> EvaluationReport:
        if output_type == "sentiment":
            evaluation_type, evaluation_config = "sentiment", {"source": "user_messages"}
        else:
            evaluation_type, evaluation_config = "llm_judge", {"prompt": "test prompt"}
        evaluation = Evaluation.objects.create(
            team=team,
            name=name,
            evaluation_type=evaluation_type,
            evaluation_config=evaluation_config,
            output_type=output_type,
            output_config={},
            target=target,
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

    def _emit_eval_events(
        self,
        team: Team,
        evaluation_id: str,
        timestamps: list[dt.datetime],
        extra_properties: dict | None = None,
    ) -> None:
        for index, ts in enumerate(timestamps):
            _create_event(
                team=team,
                event="$ai_evaluation",
                distinct_id=f"d-{evaluation_id}-{index}",
                timestamp=ts,
                properties={"$ai_evaluation_id": evaluation_id, **(extra_properties or {})},
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

    def test_split_after_a_timeout_counts_a_midpoint_event_exactly_once(self):
        # An event on the split boundary must count once. Dropped, a report at its threshold
        # stops firing; counted twice, a report below its threshold fires early.
        midpoint = self.T0 + (self.NOW - self.T0) / 2
        timestamps = [self.T0 + dt.timedelta(hours=1), midpoint, self.NOW - dt.timedelta(hours=1)]
        at_threshold = self._create_report(self.team, threshold=3, since=self.T0, name="at threshold")
        self._emit_eval_events(self.team, str(at_threshold.evaluation_id), timestamps)
        above_threshold = self._create_report(self.team, threshold=4, since=self.T0, name="above threshold")
        self._emit_eval_events(self.team, str(above_threshold.evaluation_id), timestamps)

        attempts = 0

        def time_out_the_first_attempt(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ClickHouseQueryTimeOut()
            return execute_hogql_query(*args, **kwargs)

        with patch("posthog.hogql.query.execute_hogql_query", side_effect=time_out_the_first_attempt):
            results = _check_count_triggered_eval_reports_batch(
                [str(at_threshold.id), str(above_threshold.id)], self.NOW
            )

        self.assertEqual(attempts, 3)
        due_by_id = {r.report_id: r.due for r in results}
        self.assertTrue(due_by_id[str(at_threshold.id)])
        self.assertFalse(due_by_id[str(above_threshold.id)])

    def test_events_after_check_time_are_excluded(self):
        # An event timestamped after the check's `now` must not count — guards the explicit
        # upper bound that keeps the scan from silently reading past the check time.
        report = self._create_report(self.team, threshold=1, since=self.T0, name="future")
        self._emit_eval_events(self.team, str(report.evaluation_id), [self.NOW + dt.timedelta(hours=1)])

        results = _check_count_triggered_eval_reports_batch([str(report.id)], self.NOW)

        self.assertFalse(results[0].due)

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

    def test_sentiment_reports_are_checked_with_their_own_predicate(self):
        # The loader must not restrict to boolean output types — a count-triggered sentiment
        # report would silently resolve not_deliverable forever — and sentiment events must be
        # counted with the sentiment predicate, not the boolean one.
        boolean_report = self._create_report(self.team, threshold=1, since=self.T0, name="bool")
        self._emit_eval_events(self.team, str(boolean_report.evaluation_id), [self.T0 + dt.timedelta(hours=1)])

        sentiment_report = self._create_report(
            self.team, threshold=2, since=self.T0, name="sent", output_type="sentiment"
        )
        for index, ts in enumerate([self.T0 + dt.timedelta(hours=1), self.T0 + dt.timedelta(hours=2)]):
            _create_event(
                team=self.team,
                event="$ai_evaluation",
                distinct_id=f"sent-{index}",
                timestamp=ts,
                properties={
                    "$ai_evaluation_id": str(sentiment_report.evaluation_id),
                    "$ai_evaluation_result_type": "sentiment",
                    "$ai_sentiment_label": "negative",
                },
            )

        results = _check_count_triggered_eval_reports_batch(
            [str(boolean_report.id), str(sentiment_report.id)], self.NOW
        )

        by_id = {r.report_id: r for r in results}
        self.assertIsNone(by_id[str(sentiment_report.id)].skipped_reason)
        self.assertTrue(by_id[str(sentiment_report.id)].due)
        self.assertTrue(by_id[str(boolean_report.id)].due)

    @parameterized.expand([("boolean",), ("sentiment",)])
    def test_skipped_runs_are_excluded_from_counts(self, output_type: str) -> None:
        # Sentiment's event_predicate requires the result_type property; boolean's accepts null.
        base_props = {"$ai_evaluation_result_type": output_type} if output_type == "sentiment" else {}
        skipped_props = {**base_props, "$ai_evaluation_skipped": True, "$ai_evaluation_skip_reason": "no_user_messages"}
        in_window = [self.T0 + dt.timedelta(hours=1), self.T0 + dt.timedelta(hours=2)]

        # 2 real runs + 1 skipped vs threshold 3: due only if the skipped run leaks into the count.
        report_not_due = self._create_report(
            self.team, threshold=3, since=self.T0, name=f"skip-not-due-{output_type}", output_type=output_type
        )
        self._emit_eval_events(self.team, str(report_not_due.evaluation_id), in_window, extra_properties=base_props)
        self._emit_eval_events(
            self.team,
            str(report_not_due.evaluation_id),
            [self.T0 + dt.timedelta(minutes=90)],
            extra_properties=skipped_props,
        )

        # Control: same events vs threshold 2 stays due, so the exclusion can't over-filter real runs.
        report_due = self._create_report(
            self.team, threshold=2, since=self.T0, name=f"skip-due-{output_type}", output_type=output_type
        )
        self._emit_eval_events(self.team, str(report_due.evaluation_id), in_window, extra_properties=base_props)
        self._emit_eval_events(
            self.team,
            str(report_due.evaluation_id),
            [self.T0 + dt.timedelta(minutes=90)],
            extra_properties=skipped_props,
        )

        results = _check_count_triggered_eval_reports_batch([str(report_not_due.id), str(report_due.id)], self.NOW)

        due_by_id = {r.report_id: r.due for r in results}
        self.assertFalse(due_by_id[str(report_not_due.id)])
        self.assertTrue(due_by_id[str(report_due.id)])

    def test_trace_target_reports_exclude_generation_events(self):
        # The batched countIf must carry the evaluation's target predicate like the
        # single-report query does: after an evaluation switches to the trace target,
        # stale generation-target events must not keep counting toward the threshold.
        switched = self._create_report(self.team, threshold=2, since=self.T0, name="switched", target="trace")
        for index, (ts, target_type) in enumerate(
            [
                # Two generation-shaped events (tagged + untagged legacy) and one trace event:
                # counting the generation ones would wrongly cross the threshold of 2.
                (self.T0 + dt.timedelta(hours=1), "generation_uuid"),
                (self.T0 + dt.timedelta(minutes=90), None),
                (self.T0 + dt.timedelta(hours=2), "trace_id"),
            ]
        ):
            properties = {"$ai_evaluation_id": str(switched.evaluation_id)}
            if target_type is not None:
                properties["$ai_target_type"] = target_type
            _create_event(
                team=self.team,
                event="$ai_evaluation",
                distinct_id=f"switched-{index}",
                timestamp=ts,
                properties=properties,
            )

        # Trace events must still count for a trace report (the predicate isn't over-strict).
        trace_only = self._create_report(self.team, threshold=1, since=self.T0, name="trace-only", target="trace")
        _create_event(
            team=self.team,
            event="$ai_evaluation",
            distinct_id="trace-only-0",
            timestamp=self.T0 + dt.timedelta(hours=1),
            properties={"$ai_evaluation_id": str(trace_only.evaluation_id), "$ai_target_type": "trace_id"},
        )

        results = _check_count_triggered_eval_reports_batch([str(switched.id), str(trace_only.id)], self.NOW)

        by_id = {r.report_id: r for r in results}
        self.assertFalse(by_id[str(switched.id)].due)
        self.assertTrue(by_id[str(trace_only.id)].due)

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
