import json
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    BaseMathType,
    ChartDisplayType,
    EventsNode,
    HogQLQuery,
    IntervalType,
    TrendsFilter,
    TrendsQuery,
)

from posthog.caching.insight_result import InsightResult
from posthog.temporal.ai.anomaly_investigation.tools import (
    InvestigationToolkit,
    RunHogQLQueryArgs,
    _run_detector_simulation,
    rename_shadowing_aliases,
)

from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.models import Insight


def _trend_result(label: str, data: list[float]) -> dict[str, Any]:
    dates = [f"2026-07-{day:02d}" for day in range(1, len(data) + 1)]
    return {"data": data, "days": dates, "label": label}


@patch("products.alerts.backend.evaluation.detector.calculate_for_query_based_insight")
def test_run_detector_simulation_returns_the_alerts_configured_series(mock_calculate: MagicMock) -> None:
    configured_series = [1000.0, 1100.0, 1000.0, 900.0] * 3
    mock_calculate.return_value = InsightResult(
        result=[
            _trend_result("series 0", [10.0, 11.0, 10.0, 9.0] * 3),
            _trend_result("series 1", [100.0, 110.0, 100.0, 90.0] * 3),
            _trend_result("series 2", configured_series),
        ],
        columns=[],
        timezone="UTC",
        last_refresh=None,
        cache_key="",
        is_cached=False,
    )

    insight = MagicMock(spec=Insight)
    insight.query = TrendsQuery(
        series=[
            EventsNode(event="series_0", math=BaseMathType.TOTAL),
            EventsNode(event="series_1", math=BaseMathType.TOTAL),
            EventsNode(event="series_2", math=BaseMathType.TOTAL),
        ],
        trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        interval=IntervalType.DAY,
    ).model_dump()
    alert = MagicMock(spec=AlertConfiguration)
    alert.insight = insight
    alert.config = {"type": "TrendsAlertConfig", "series_index": 2}
    alert.detector_config = {"type": "zscore", "threshold": 0.9, "window": 10}
    alert.created_by = None

    result = _run_detector_simulation(alert=alert, team=MagicMock(), date_from=None)

    assert not isinstance(result, str)
    assert result["data"] == configured_series[:-1]


@patch("products.alerts.backend.evaluation.hogql.calculate_for_query_based_insight")
def test_run_detector_simulation_scores_the_configured_column_of_a_multi_numeric_sql_result(
    mock_calculate: MagicMock,
) -> None:
    # zscore needs 31 samples; give the series headroom so it scores.
    failure_rate = [10.0 + (i % 7) for i in range(40)]
    run_count = [1800.0 + i for i in range(len(failure_rate))]
    days = [f"2026-07-{(i % 30) + 1:02d}" for i in range(len(failure_rate))]
    # Two numeric columns: without the alert's config the simulation can't pick which one to score.
    rows = [[days[i], failure_rate[i], run_count[i]] for i in range(len(failure_rate))]
    mock_calculate.return_value = InsightResult(
        result=rows,
        columns=["day", "failure_rate_pct", "run_count"],
        timezone="UTC",
        last_refresh=None,
        cache_key="",
        is_cached=False,
    )

    insight = MagicMock(spec=Insight)
    insight.query = HogQLQuery(query="SELECT day, failure_rate_pct, run_count FROM ci_runs").model_dump()
    alert = MagicMock(spec=AlertConfiguration)
    alert.insight = insight
    alert.config = {"type": "HogQLAlertConfig", "column": "failure_rate_pct", "evaluation": "last_row"}
    alert.detector_config = {"type": "zscore", "threshold": 0.9, "window": 7}
    alert.created_by = None

    result = _run_detector_simulation(alert=alert, team=MagicMock(), date_from=None)

    assert not isinstance(result, str)
    # Scores failure_rate_pct, not run_count. The data is the tail of the configured column.
    assert result["data"] == failure_rate[-len(result["data"]) :]


@parameterized.expand(
    [
        # The shape the agent keeps writing, and the one the engine rejects.
        ("aggregate_shadowing_its_column", "SELECT sum(runs) AS runs FROM t", {"runs": "runs_sum"}),
        ("qualified_operand", "SELECT max(t.cost) AS cost FROM t", {"cost": "cost_max"}),
        # A non-aggregate alias of the same name is accepted, so rewriting it would break a
        # working query while chasing an unrelated error.
        ("non_aggregate_left_alone", "SELECT toStartOfHour(h) AS h FROM t", {}),
        ("distinct_alias_left_alone", "SELECT sum(runs) AS run_total FROM t", {}),
    ]
)
def test_only_self_shadowing_aggregates_are_renamed(_name: str, sql: str, expected: dict[str, str]) -> None:
    rewritten, renames = rename_shadowing_aliases(sql)

    assert renames == expected
    for old, new in expected.items():
        assert f"AS {new}" in rewritten
        assert f"AS {old} " not in f"{rewritten} "
    if not expected:
        assert rewritten == sql


async def test_alias_conflict_is_retried_and_reported_as_readable() -> None:
    response = MagicMock(results=[[7]], columns=["runs_sum"])
    with patch(
        "posthog.temporal.ai.anomaly_investigation.tools.execute_hogql_query",
        side_effect=[Exception("Cyclic aliases"), response],
    ) as mock_execute:
        result = await InvestigationToolkit(team=MagicMock()).run_hogql_query(
            RunHogQLQueryArgs(query="SELECT sum(runs) AS runs FROM hourly_spend")
        )

    payload = json.loads(result)
    assert payload["rows"] == [[7]]
    assert payload["renamed_aliases"] == {"runs": "runs_sum"}
    assert "SELECT sum(runs) AS runs_sum FROM hourly_spend" == mock_execute.call_args.kwargs["query"]


async def test_an_unfixable_error_tells_the_agent_the_data_is_not_the_problem() -> None:
    with patch(
        "posthog.temporal.ai.anomaly_investigation.tools.execute_hogql_query",
        side_effect=Exception("Unknown table 'hourly_spend'"),
    ) as mock_execute:
        result = await InvestigationToolkit(team=MagicMock()).run_hogql_query(
            RunHogQLQueryArgs(query="SELECT count() AS c FROM hourly_spend")
        )

    # No retry: nothing about this error a renamed alias fixes.
    assert mock_execute.call_count == 1
    assert "defect in the query text" in result
    assert "Do not report a data source as unreadable" in result
