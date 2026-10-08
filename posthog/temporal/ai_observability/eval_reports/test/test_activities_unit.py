import datetime as dt

import pytest
from unittest.mock import MagicMock, Mock, patch

from django.utils import timezone

from posthog.temporal.ai_observability.eval_reports.activities import (
    _count_eval_results_for_report,
    _find_nth_eval_timestamp,
    _update_next_delivery_date,
)
from posthog.temporal.ai_observability.eval_reports.targets import target_event_predicate
from posthog.temporal.ai_observability.eval_reports.types import UpdateNextDeliveryDateInput


@pytest.mark.parametrize(
    ("generation_status,record_attempt,advance_data_cursor,expects_delivered_advance,expected_update_fields"),
    [
        ("metrics_unavailable", True, None, False, ["next_delivery_date", "last_attempted_at"]),
        ("completed", True, None, True, ["next_delivery_date", "last_attempted_at", "last_delivered_at"]),
        ("completed", False, True, True, ["last_delivered_at"]),
    ],
    ids=["unavailable_legacy", "completed_legacy", "completed_cursor_only"],
)
@patch("products.ai_observability.backend.models.evaluation_reports.EvaluationReport.objects.get")
def test_updates_automatic_report_timing(
    get_report: MagicMock,
    generation_status: str,
    record_attempt: bool,
    advance_data_cursor: bool | None,
    expects_delivered_advance: bool,
    expected_update_fields: list[str],
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

    assert report.last_attempted_at == (period_end if record_attempt else last_attempted)
    assert report.last_delivered_at == (period_end if expects_delivered_advance else last_delivered)
    if record_attempt:
        report.set_next_delivery_date.assert_called_once_with()
    else:
        report.set_next_delivery_date.assert_not_called()
    report.save.assert_called_once_with(update_fields=expected_update_fields)


@pytest.mark.parametrize(
    "target,expected",
    [
        ("session", "properties.$ai_target_type = 'session_id'"),
        ("trace", "properties.$ai_target_type = 'trace_id'"),
    ],
)
def test_target_event_predicate_per_target(target: str, expected: str) -> None:
    assert target_event_predicate(target) == expected


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
