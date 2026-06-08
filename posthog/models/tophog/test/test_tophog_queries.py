from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models.tophog.queries import query_tophog_filter_options, query_tophog_metrics
from posthog.models.tophog.sql import DATA_TABLE_NAME, TRUNCATE_TOPHOG_TABLE_SQL

TS = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
DATE_FROM = datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC)
DATE_TO = datetime(2024, 1, 15, 23, 59, 59, tzinfo=UTC)


def _map_literal(d: dict[str, str]) -> str:
    pairs = ", ".join(f"'{k}', '{v}'" for k, v in d.items())
    return f"map({pairs})"


def _insert_rows(rows: list[tuple]) -> None:
    if not rows:
        return
    values = []
    for ts, metric, type_, key, value, count, pipeline, lane in rows:
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        map_lit = _map_literal(key)
        values.append(f"('{ts_str}', '{metric}', '{type_}', {map_lit}, {value}, {count}, '{pipeline}', '{lane}')")
    sql = f"""
        INSERT INTO {DATA_TABLE_NAME}
            (timestamp, metric, type, key, value, count, pipeline, lane)
        VALUES {", ".join(values)}
    """
    sync_execute(sql)


class TestTopHogQueries(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_TOPHOG_TABLE_SQL())

    def test_no_data_returns_empty(self):
        results = query_tophog_metrics(DATE_FROM, DATE_TO)
        assert results == []

    @parameterized.expand(
        [
            ("sum_aggregation", "sum", [10.0, 20.0, 30.0], 60.0),
            ("max_aggregation", "max", [10.0, 20.0, 30.0], 30.0),
        ]
    )
    def test_single_key_aggregation(self, _name, agg_type, values, expected_total):
        rows = [(TS, "latency", agg_type, {"fn": "process"}, v, 1, "events", "fast") for v in values]
        _insert_rows(rows)

        results = query_tophog_metrics(DATE_FROM, DATE_TO)
        assert len(results) == 1
        assert results[0]["total"] == pytest.approx(expected_total, abs=10 ** (-5) * 0.5)
        assert results[0]["obs"] == len(values)

    def test_avg_aggregation_weighted(self):
        _insert_rows(
            [
                (TS, "latency", "avg", {"fn": "process"}, 10.0, 100, "events", "fast"),
                (TS, "latency", "avg", {"fn": "process"}, 20.0, 300, "events", "fast"),
            ]
        )

        results = query_tophog_metrics(DATE_FROM, DATE_TO)
        assert len(results) == 1
        # weighted avg: (10*100 + 20*300) / (100+300) = 7000/400 = 17.5
        assert results[0]["total"] == pytest.approx(17.5, abs=10 ** (-5) * 0.5)
        assert results[0]["obs"] == 400

    def test_top_10_ranking(self):
        rows = [(TS, "latency", "sum", {"fn": f"func_{i}"}, float(i), 1, "events", "fast") for i in range(15)]
        _insert_rows(rows)

        results = query_tophog_metrics(DATE_FROM, DATE_TO)
        assert len(results) == 10
        totals = [r["total"] for r in results]
        assert totals == sorted(totals, reverse=True)
        assert totals[0] == 14.0

    def test_pipeline_filter(self):
        _insert_rows(
            [
                (TS, "latency", "sum", {"fn": "a"}, 10.0, 1, "events", "fast"),
                (TS, "latency", "sum", {"fn": "b"}, 20.0, 1, "recordings", "fast"),
            ]
        )

        results = query_tophog_metrics(DATE_FROM, DATE_TO, pipeline="events")
        assert len(results) == 1
        assert results[0]["key"] == {"fn": "a"}

    def test_lane_filter(self):
        _insert_rows(
            [
                (TS, "latency", "sum", {"fn": "a"}, 10.0, 1, "events", "fast"),
                (TS, "latency", "sum", {"fn": "b"}, 20.0, 1, "events", "slow"),
            ]
        )

        results = query_tophog_metrics(DATE_FROM, DATE_TO, lane="slow")
        assert len(results) == 1
        assert results[0]["key"] == {"fn": "b"}

    def test_both_filters(self):
        _insert_rows(
            [
                (TS, "latency", "sum", {"fn": "a"}, 10.0, 1, "events", "fast"),
                (TS, "latency", "sum", {"fn": "b"}, 20.0, 1, "events", "slow"),
                (TS, "latency", "sum", {"fn": "c"}, 30.0, 1, "recordings", "fast"),
                (TS, "latency", "sum", {"fn": "d"}, 40.0, 1, "recordings", "slow"),
            ]
        )

        results = query_tophog_metrics(DATE_FROM, DATE_TO, pipeline="recordings", lane="slow")
        assert len(results) == 1
        assert results[0]["key"] == {"fn": "d"}

    def test_no_filter_aggregates_across_pipelines(self):
        _insert_rows(
            [
                (TS, "latency", "sum", {"fn": "shared"}, 10.0, 1, "events", "fast"),
                (TS, "latency", "sum", {"fn": "shared"}, 20.0, 1, "recordings", "slow"),
            ]
        )

        results = query_tophog_metrics(DATE_FROM, DATE_TO)
        assert len(results) == 1
        assert results[0]["total"] == pytest.approx(30.0, abs=10 ** (-5) * 0.5)
        assert results[0]["pipelines"] == ["events", "recordings"]
        assert results[0]["lanes"] == ["fast", "slow"]

    def test_filter_options(self):
        _insert_rows(
            [
                (TS, "latency", "sum", {"fn": "a"}, 1.0, 1, "events", "fast"),
                (TS, "latency", "sum", {"fn": "b"}, 1.0, 1, "events", "slow"),
                (TS, "latency", "sum", {"fn": "c"}, 1.0, 1, "recordings", "fast"),
            ]
        )

        pipelines, lanes = query_tophog_filter_options(DATE_FROM, DATE_TO)
        assert pipelines == ["events", "recordings"]
        assert lanes == ["fast", "slow"]
