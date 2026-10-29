from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.evaluation_result import EvaluationResult

from .rows import EVALUATION_ID, T0, make_evaluation_result_row

DETECTOR = {"true_is_failure": True}
AT_LEAST_0_7 = {"passing_rule": {"operator": "gte", "threshold": 0.7}}
BILLING_ONLY = {
    "options": [{"key": "billing", "label": "Billing"}, {"key": "refund", "label": "Refund"}],
    "passing_rule": {"categories": ["billing"]},
}


def evaluation_result(overrides: dict[str, Any], output_config: dict[str, Any] | None = None) -> EvaluationResult:
    return EvaluationResult.from_row(
        make_evaluation_result_row(**overrides), trace_id="trace-1", output_config=output_config or {}
    )


@parameterized.expand(
    [
        ("a true result", {}, {}, "pass", "True"),
        ("a false result", {"result": "false"}, {}, "fail", "False"),
        ("a result written as True", {"result": "True"}, {}, "pass", "True"),
        ("a true result from a detector", {}, DETECTOR, "fail", "True"),
        ("a false result from a detector", {"result": "false"}, DETECTOR, "pass", "False"),
        (
            "a skipped run whose result is still false",
            {"skipped": "true", "result": "false"},
            {},
            "inconclusive",
            "Skipped",
        ),
        ("a missing result", {"result": None}, {}, "inconclusive", "N/A"),
        ("a result marked not applicable", {"applicable": "false"}, {}, "inconclusive", "N/A"),
        ("a score with no passing rule", {"result_type": "numeric", "score": "0.82"}, {}, "unrated", "0.82"),
        ("a score under the threshold", {"result_type": "numeric", "score": "0.4"}, AT_LEAST_0_7, "fail", "0.4"),
        ("a score over the threshold", {"result_type": "numeric", "score": "0.9"}, AT_LEAST_0_7, "pass", "0.9"),
        (
            "a long score rounded to two places",
            {"result_type": "numeric", "score": "12.3456"},
            {},
            "unrated",
            "12.35",
        ),
        ("a whole score", {"result_type": "numeric", "score": "3"}, {}, "unrated", "3"),
        (
            "a score whose rounding would flip the verdict",
            {"result_type": "numeric", "score": "0.6999"},
            AT_LEAST_0_7,
            "fail",
            "0.6999",
        ),
        ("a numeric run with no score", {"result_type": "numeric"}, {}, "inconclusive", "No score"),
        ("a numeric run with an empty score", {"result_type": "numeric", "score": ""}, {}, "inconclusive", "No score"),
        (
            "a numeric run marked not applicable",
            {"result_type": "numeric", "score": "0.5", "applicable": "false"},
            {},
            "inconclusive",
            "N/A",
        ),
        (
            "a stored threshold that is not a number",
            {"result_type": "numeric", "score": "0.4"},
            {"passing_rule": {"operator": "gte", "threshold": "0.7"}},
            "unrated",
            "0.4",
        ),
        (
            "a stored rule with an unknown operator",
            {"result_type": "numeric", "score": "0.4"},
            {"passing_rule": {"operator": "gt", "threshold": 0.7}},
            "unrated",
            "0.4",
        ),
        (
            "categories inside the passing rule",
            {"result_type": "categorical", "categories": '["billing"]'},
            BILLING_ONLY,
            "pass",
            "Billing",
        ),
        (
            "categories outside the passing rule",
            {"result_type": "categorical", "categories": '["billing", "refund"]'},
            BILLING_ONLY,
            "fail",
            "Billing, Refund",
        ),
        (
            "a category with no option keeps its key",
            {"result_type": "categorical", "categories": '["other"]'},
            {},
            "unrated",
            "other",
        ),
        (
            "an applicable run with no categories",
            {"result_type": "categorical", "applicable": "true"},
            BILLING_ONLY,
            "fail",
            "No categories",
        ),
        (
            "categories that are not JSON",
            {"result_type": "categorical", "categories": "billing"},
            BILLING_ONLY,
            "inconclusive",
            "No result",
        ),
        (
            "categories marked not applicable",
            {"result_type": "categorical", "categories": '["billing"]', "applicable": "false"},
            BILLING_ONLY,
            "inconclusive",
            "N/A",
        ),
        ("a positive sentiment", {"result_type": "sentiment", "sentiment_label": "positive"}, {}, "pass", "Positive"),
        ("a neutral sentiment", {"result_type": "sentiment", "sentiment_label": "neutral"}, {}, "unrated", "Neutral"),
        ("a negative sentiment", {"result_type": "sentiment", "sentiment_label": "negative"}, {}, "fail", "Negative"),
        ("an unlabelled sentiment", {"result_type": "sentiment"}, {}, "inconclusive", "Unknown"),
        (
            "a sentiment run with no result type",
            {"evaluation_type": "sentiment", "sentiment_label": "positive"},
            {},
            "pass",
            "Positive",
        ),
    ]
)
def test_outcome_and_label(
    _name: str, overrides: dict[str, Any], output_config: dict[str, Any], outcome: str, label: str
) -> None:
    result = evaluation_result(overrides, output_config)

    assert (result.outcome, result.label) == (outcome, label)


@parameterized.expand(
    [
        (
            "a generation result",
            {"target_event_id": "gen-1"},
            ("gen-1", False, EVALUATION_ID, "Answers the question", "Direct answer."),
        ),
        ("a trace-level result", {}, ("trace-1", False, EVALUATION_ID, "Answers the question", "Direct answer.")),
        (
            "a backfilled result",
            {"backfill_id": "backfill-1"},
            ("trace-1", True, EVALUATION_ID, "Answers the question", "Direct answer."),
        ),
        (
            "a result from outside whose evaluation id is not a UUID",
            {"evaluation_id": "not-a-uuid"},
            ("trace-1", False, None, "Answers the question", "Direct answer."),
        ),
        (
            "a result from outside with no id, name or reasoning",
            {"evaluation_id": None, "evaluation_name": None, "reasoning": ""},
            ("trace-1", False, None, "Unknown evaluation", None),
        ),
    ]
)
def test_target_name_and_backfill(_name: str, overrides: dict[str, Any], expected: tuple[Any, ...]) -> None:
    result = evaluation_result(overrides)

    assert (
        result.target_node_id,
        result.is_backfill,
        result.evaluation_id,
        result.name,
        result.reasoning,
    ) == expected


@parameterized.expand(
    [
        ("a numeric result", {"result_type": "numeric", "score": "0.82"}, 0.82),
        (
            "a numeric result marked not applicable",
            {"result_type": "numeric", "score": "0.82", "applicable": "false"},
            None,
        ),
        ("a boolean result", {}, None),
    ]
)
def test_score_is_the_numeric_result(_name: str, overrides: dict[str, Any], score: float | None) -> None:
    assert evaluation_result(overrides).score == score


@parameterized.expand(
    [
        ("the run start time", "2026-09-21T10:00:00+00:00", datetime(2026, 9, 21, 10, 0, tzinfo=UTC)),
        ("a start time without a zone, as UTC", "2026-09-21T10:00:00", datetime(2026, 9, 21, 10, 0, tzinfo=UTC)),
        ("the event time when the start time is not a date", "yesterday", T0),
        ("the event time when there is no start time", None, T0),
    ]
)
def test_produced_at_is(_name: str, start_time: str | None, produced_at: datetime) -> None:
    assert evaluation_result({"start_time": start_time}).produced_at == produced_at
