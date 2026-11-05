import json
import uuid
import datetime as dt

import pytest

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

pytestmark = pytest.mark.django_db

TEAM_ID = 990_001
SERIES_FINGERPRINT = 7
HOUR = dt.datetime(2026, 10, 1, 12, tzinfo=dt.UTC)

# The SDK changes its bucket layout between the second and the third point of one series-hour.
POINTS: list[tuple[dt.datetime, list[float]]] = [
    (HOUR + dt.timedelta(minutes=1), [1.0, 5.0, 10.0]),
    (HOUR + dt.timedelta(minutes=2), [1.0, 5.0, 10.0]),
    (HOUR + dt.timedelta(minutes=3), [0.5, 1.0, 2.5, 5.0]),
    (HOUR + dt.timedelta(minutes=4), [0.5, 1.0, 2.5, 5.0]),
]


def _input_row(timestamp: dt.datetime, bounds: list[float]) -> str:
    formatted = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
    return json.dumps(
        {
            "uuid": str(uuid.uuid4()),
            "team_id": TEAM_ID,
            "metric_name": "http.server.duration",
            "series_fingerprint": SERIES_FINGERPRINT,
            "resource_fingerprint": 0,
            "timestamp": formatted,
            "observed_timestamp": formatted,
            "original_expiry_timestamp": "2200-01-01 00:00:00.000000",
            "service_name": "checkout",
            "metric_type": "histogram",
            "value": 1.0,
            "count": len(bounds) + 1,
            "histogram_bounds": bounds,
            "histogram_counts": [1] * (len(bounds) + 1),
            "trace_id": "",
            "span_id": "",
            "trace_flags": 0,
            "has_labels": True,
            "unit": "ms",
            "aggregation_temporality": "delta",
            "is_monotonic": False,
            "instrumentation_scope": "",
            "resource_attributes": {},
            "attributes": {},
        }
    )


def _insert(points: list[tuple[dt.datetime, list[float]]]) -> None:
    payload = "\n".join(_input_row(timestamp, bounds) for timestamp, bounds in points)
    sync_execute(f"INSERT INTO metrics4_input FORMAT JSONEachRow {payload}")


@pytest.fixture(autouse=True)
def _empty_samples(django_db_setup) -> None:
    sync_execute("TRUNCATE TABLE IF EXISTS metrics4_samples")


@parameterized.expand(
    [
        ("one_insert_block", False),
        ("separate_parts_merged", True),
    ]
)
def test_each_point_keeps_the_bounds_it_was_sent_with(_name: str, merge_parts: bool) -> None:
    if merge_parts:
        for point in POINTS:
            _insert([point])
        sync_execute("OPTIMIZE TABLE metrics4_samples FINAL")
    else:
        _insert(POINTS)

    rows = sync_execute(
        "SELECT timestamp_arr, histogram_bounds_arr, histogram_counts_arr FROM metrics4_samples "
        "WHERE team_id = %(team_id)s AND series_fingerprint = %(series)s",
        {"team_id": TEAM_ID, "series": SERIES_FINGERPRINT},
    )

    assert len(rows) == 1
    timestamps, bounds, counts = rows[0]
    assert len(bounds) == len(timestamps) == len(counts)
    by_timestamp = {ts.replace(tzinfo=dt.UTC): (b, c) for ts, b, c in zip(timestamps, bounds, counts)}
    assert by_timestamp == {ts: (b, [1] * (len(b) + 1)) for ts, b in POINTS}
