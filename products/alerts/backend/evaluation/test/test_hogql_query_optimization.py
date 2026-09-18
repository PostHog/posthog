from copy import deepcopy

import pytest

from products.alerts.backend.evaluation.hogql_query_optimization import optimize_last_row_query

SQL = """
SELECT toStartOfHour(timestamp) AS bucket, count() AS value
FROM events
WHERE timestamp >= toStartOfHour(now()) - INTERVAL 48 HOUR
  AND timestamp < toStartOfHour(now())
  AND event = 'signup'
GROUP BY bucket
ORDER BY bucket ASC
"""


@pytest.mark.parametrize(
    "aggregate",
    [
        "count()",
        "countIf(event = 'signup')",
        "uniqExact(person_id)",
        "uniqIf(person_id, event = 'signup') - uniqIf(person_id, event = 'cancel')",
    ],
)
def test_shortens_scan_without_mutating_saved_query(aggregate: str) -> None:
    query: dict = {
        "kind": "DataVisualizationNode",
        "display": "ActionsLineGraph",
        "source": {
            "kind": "HogQLQuery",
            "query": SQL.replace("count()", aggregate),
            "filters": {"dateRange": {"date_from": "-7d"}},
        },
    }
    original = deepcopy(query)
    optimized = optimize_last_row_query(query, column="value")
    assert optimized is not None
    assert query == original
    assert optimized["display"] == query["display"]
    assert "toStartOfHour(minus(toStartOfHour(now()), toIntervalHour(2)))" in optimized["source"]["query"]
    assert optimized["source"]["filters"] == original["source"]["filters"]
    assert "toIntervalHour(48)" in optimized["source"]["query"]
    assert "signup" in optimized["source"]["query"]


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
        SQL.replace("48 HOUR", "49999 HOUR"),
    ],
)
def test_unsupported_queries_keep_original_execution(sql: str) -> None:
    assert optimize_last_row_query({"kind": "HogQLQuery", "query": sql}, column="value") is None


def test_inferred_value_column_keeps_full_query() -> None:
    assert optimize_last_row_query({"kind": "HogQLQuery", "query": SQL}, column=None) is None


@pytest.mark.parametrize(
    "hours,limit,eligible", [(48, "", True), (336, "", False), (336, " LIMIT 1000", True), (48, " LIMIT 20", False)]
)
def test_preserves_original_pagination(hours: int, limit: str, eligible: bool) -> None:
    sql = SQL.replace("48 HOUR", f"{hours} HOUR") + limit
    optimized = optimize_last_row_query({"kind": "HogQLQuery", "query": sql}, column="value")
    assert (optimized is not None) == eligible
