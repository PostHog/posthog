from __future__ import annotations

from typing import Any

import pytest

from braintrust import Score

from ee.hogai.eval.sandboxed.mcp_benchmark.cases import load_benchmark_cases
from ee.hogai.eval.sandboxed.mcp_benchmark.scorers import QueryExecutes, SuccessCriteria


def test_load_benchmark_cases_translates_the_sql_category() -> None:
    cases = load_benchmark_cases("sql")
    names = [case.name for case in cases]
    assert "sql-daily-event-volume" in names
    assert "sql-top-events" in names
    for case in cases:
        assert case.prompt
        assert isinstance(case.expected["success_criteria"], str) and case.expected["success_criteria"]
        assert case.metadata["category"] == "sql"
        assert isinstance(case.metadata["expected_tools"], list) and case.metadata["expected_tools"]


def test_load_benchmark_cases_rejects_unknown_categories() -> None:
    with pytest.raises(ValueError, match="no-such-category"):
        load_benchmark_cases("no-such-category")


@pytest.mark.parametrize(
    "output, expected_score, reason_substring",
    [
        pytest.param(
            {"query": "SELECT 1", "results": [[1]], "error": ""},
            1.0,
            None,
            id="query_ran_and_returned_rows",
        ),
        pytest.param(None, 0.0, "No output", id="missing_output"),
        pytest.param({"query": "", "results": [], "error": ""}, 0.0, "no SQL query", id="no_query_generated"),
        pytest.param(
            {"query": "SELECT bogus", "results": [], "error": "Unknown column"},
            0.0,
            "Query failed",
            id="query_errored",
        ),
        pytest.param({"query": "SELECT 1", "results": [], "error": ""}, 0.0, "no rows", id="empty_result"),
    ],
)
def test_query_executes_scorer(
    output: dict[str, Any] | None, expected_score: float, reason_substring: str | None
) -> None:
    score = QueryExecutes()._run_eval_sync(output)
    assert score.score == expected_score
    if reason_substring:
        assert reason_substring in score.metadata["reason"]


@pytest.mark.parametrize(
    "output, expected, reason_substring",
    [
        pytest.param({"query": "", "results": []}, {"success_criteria": "c"}, "no SQL query", id="no_query"),
        pytest.param(
            {"query": "SELECT 1", "results": [], "error": "boom"},
            {"success_criteria": "c"},
            "Query failed",
            id="errored_query",
        ),
        pytest.param({"query": "SELECT 1", "results": [[1]]}, {}, "success_criteria", id="missing_criteria"),
    ],
)
def test_success_criteria_short_circuits_without_llm(
    output: dict[str, Any], expected: dict[str, Any], reason_substring: str
) -> None:
    prepared = SuccessCriteria()._prepare(output, expected)
    assert isinstance(prepared, Score)
    assert prepared.score == 0.0
    assert reason_substring in prepared.metadata["reason"]


def test_success_criteria_prepares_judge_variables_with_truncation() -> None:
    output = {
        "prompt": "How many events per day?",
        "query": "SELECT day, count() FROM events GROUP BY day",
        "columns": ["day", "count"],
        "results": [["2026-07-01", 10]] * 4000,
        "error": "",
    }
    prepared = SuccessCriteria()._prepare(output, {"success_criteria": "Returns a per-day event count."})
    assert not isinstance(prepared, Score)
    assert prepared["expected"] == {"criteria": "Returns a per-day event count."}
    assert prepared["output"]["query"] == output["query"]
    assert "[truncated for judge]" in prepared["output"]["results"]
