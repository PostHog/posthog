from copy import deepcopy

import pytest

from products.alerts.backend.evaluation.detector_history_eligibility import match_detector_series_query

SQL = """
SELECT toStartOfHour(timestamp) AS bucket, count() AS value
FROM events
WHERE timestamp >= toStartOfHour(now()) - INTERVAL 48 HOUR
  AND timestamp < toStartOfHour(now())
  AND event = 'signup'
GROUP BY bucket
ORDER BY bucket ASC
"""


def _query(sql: str = SQL) -> dict:
    return {"kind": "HogQLQuery", "query": sql}


@pytest.mark.parametrize(
    "aggregate",
    [
        "count()",
        "countIf(event = 'signup')",
        "uniqExact(person_id)",
        "uniqIf(person_id, event = 'signup') - uniqIf(person_id, event = 'cancel')",
    ],
)
@pytest.mark.parametrize("column", ["value", None])
def test_accepts_bucket_local_aggregations(aggregate: str, column: str | None) -> None:
    matched = match_detector_series_query(_query(SQL.replace("count()", aggregate)), column=column)
    assert matched is not None
    assert matched.window_hours == 48
    assert matched.column_names == ["bucket", "value"]


@pytest.mark.parametrize(
    "sql",
    [
        SQL.replace("ASC", "DESC"),
        SQL + " LIMIT 1",
        SQL.replace("ORDER BY bucket ASC", "ORDER BY bucket ASC WITH FILL"),
        SQL.replace("count()", "sum(rand())"),
        SQL.replace("count()", "row_number() OVER (ORDER BY bucket)"),
        SQL.replace("count()", "(SELECT count() FROM events)"),
        SQL.replace("GROUP BY bucket", "GROUP BY bucket, event"),
        SQL.replace("GROUP BY bucket", "GROUP BY bucket HAVING count() > 2"),
        SQL.replace("48 HOUR", "100000 HOUR"),
        SQL.replace("48 HOUR", "1 HOUR"),
        SQL.replace("timestamp <", "timestamp <="),
        SQL.replace("toStartOfHour(now())", "now()"),
        SQL.replace("AS value", "AS timestamp"),
        SQL.replace("AND event = 'signup'", "AND rand() > 0"),
        SQL.replace("FROM events", "FROM persons"),
        SQL.replace("FROM events", "FROM events SAMPLE 0.1"),
        SQL.replace("AND event = 'signup'", "AND event =~ properties.pattern"),
        SQL.replace("count()", "countIf(event IN (SELECT event FROM events))"),
        SQL.replace("count()", "countIf(timestamp >= toStartOfHour(now()) - INTERVAL 6 HOUR)"),
        SQL.replace(
            "AND event = 'signup'",
            "AND (timestamp >= toStartOfHour(now()) - INTERVAL 6 HOUR OR event = 'signup')",
        ),
        SQL.replace("AND event = 'signup'", "AND {filters}"),
        "SELECT 1",
        "not valid hogql at all",
    ],
)
def test_rejects_shapes_whose_buckets_are_not_self_contained(sql: str) -> None:
    assert match_detector_series_query(_query(sql), column="value") is None


def test_rejects_a_column_that_is_not_the_aggregate() -> None:
    assert match_detector_series_query(_query(), column="bucket") is None


@pytest.mark.parametrize(
    "hours,limit,eligible",
    [(48, "", True), (336, "", False), (336, " LIMIT 1000", True), (48, " LIMIT 20", False)],
)
def test_requires_the_full_window_to_fit_in_the_result(hours: int, limit: str, eligible: bool) -> None:
    sql = SQL.replace("48 HOUR", f"{hours} HOUR") + limit
    matched = match_detector_series_query(_query(sql), column="value")
    assert (matched is not None) == eligible
    if matched is not None:
        assert matched.window_hours == hours


def test_narrowing_tightens_the_lower_bound_and_leaves_the_saved_query_alone() -> None:
    query: dict = {
        "kind": "DataVisualizationNode",
        "display": "ActionsLineGraph",
        "source": {"kind": "HogQLQuery", "query": SQL, "filters": {"dateRange": {"date_from": "-7d"}}},
    }
    original = deepcopy(query)
    matched = match_detector_series_query(query, column="value")
    assert matched is not None

    narrowed = matched.narrowed_to(3)
    assert query == original
    assert narrowed["display"] == original["display"]
    assert narrowed["source"]["filters"] == original["source"]["filters"]
    narrowed_sql = narrowed["source"]["query"]
    assert "toIntervalHour(3)" in narrowed_sql
    assert "toIntervalHour(48)" in narrowed_sql
    assert "signup" in narrowed_sql
    # Narrowing twice must not accumulate bounds on a shared tree.
    assert matched.narrowed_to(3)["source"]["query"] == narrowed_sql


def test_narrowing_refuses_a_window_it_would_not_shorten() -> None:
    matched = match_detector_series_query(_query(), column="value")
    assert matched is not None
    with pytest.raises(ValueError):
        matched.narrowed_to(48)
