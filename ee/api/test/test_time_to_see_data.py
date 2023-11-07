import json
from dataclasses import asdict, dataclass, field
from typing import Any, List
from unittest import mock

import pytest

from posthog.client import sync_execute
from posthog.models.query_metrics.sql import (
    CREATE_METRICS_QUERY_LOG,
    CREATE_METRICS_TIME_TO_SEE,
    DROP_METRICS_QUERY_LOG,
    DROP_METRICS_TIME_TO_SEE_TABLE,
)
from posthog.test.base import APIBaseTest


@pytest.mark.usefixtures("unittest_snapshot")
class TestTimeToSeeDataApi(APIBaseTest):
    maxDiff = None
    snapshot: Any

    def setUp(self):
        super().setUp()
        try:
            sync_execute(CREATE_METRICS_TIME_TO_SEE())
            sync_execute(CREATE_METRICS_QUERY_LOG())
        except:
            pass
        self.user.is_staff = True
        self.user.save()

    def tearDown(self):
        super().tearDown()
        sync_execute(DROP_METRICS_TIME_TO_SEE_TABLE())
        sync_execute(DROP_METRICS_QUERY_LOG())

    def test_sessions_api(self):
        insert(
            "metrics_time_to_see_data",
            [
                MetricsRow(
                    session_id="456",
                    timestamp="2022-10-05 12:20:30",
                    time_to_see_data_ms=7000,
                ),
                MetricsRow(
                    session_id="123",
                    timestamp="2022-10-05 10:10:30",
                    time_to_see_data_ms=2000,
                ),
                MetricsRow(
                    session_id="123",
                    timestamp="2022-10-05 10:30:25",
                    time_to_see_data_ms=1000,
                    is_primary_interaction=False,
                ),
                MetricsRow(
                    session_id="123",
                    timestamp="2022-10-05 10:30:30",
                    time_to_see_data_ms=7000,
                ),
            ],
        )

        response = self.client.post("/api/time_to_see_data/sessions").json()
        self.assertEquals(
            response,
            [
                {
                    "duration_ms": 7000,
                    "events_count": 1,
                    "frustrating_interactions_count": 1,
                    "interactions_count": 1,
                    "session_start": "2022-10-05T12:20:23Z",
                    "session_end": "2022-10-05T12:20:30Z",
                    "session_id": "456",
                    "team_events_last_month": mock.ANY,
                    "team_id": 2,
                    "total_interaction_time_to_see_data_ms": 7000,
                    "user": mock.ANY,
                    "user_id": 123,
                },
                {
                    "duration_ms": 1202000,
                    "events_count": 3,
                    "frustrating_interactions_count": 1,
                    "interactions_count": 2,
                    "session_start": "2022-10-05T10:10:28Z",
                    "session_end": "2022-10-05T10:30:30Z",
                    "session_id": "123",
                    "team_events_last_month": mock.ANY,
                    "team_id": 2,
                    "total_interaction_time_to_see_data_ms": 9000,
                    "user": mock.ANY,
                    "user_id": 123,
                },
            ],
        )

    def test_session_events_api(self):
        insert(
            "metrics_time_to_see_data",
            [
                MetricsRow(
                    session_id="456",
                    timestamp="2022-10-05 12:20:30",
                    time_to_see_data_ms=7000,
                ),
                MetricsRow(
                    session_id="123",
                    timestamp="2022-10-05 10:10:30",
                    time_to_see_data_ms=2000,
                    primary_interaction_id="111-222-333",
                ),
                MetricsRow(
                    session_id="123",
                    timestamp="2022-10-05 10:30:25",
                    time_to_see_data_ms=1000,
                    is_primary_interaction=False,
                    primary_interaction_id="111-222-333",
                    query_id="777",
                ),
                MetricsRow(
                    session_id="123",
                    timestamp="2022-10-05 10:30:30",
                    time_to_see_data_ms=7000,
                ),
            ],
        )

        insert(
            "metrics_query_log",
            [
                QueryLogRow(
                    session_id="123",
                    timestamp="2022-10-05 10:10:30",
                    query_duration_ms=400,
                    client_query_id="111-222-333::777",
                ),
                QueryLogRow(
                    session_id="123",
                    timestamp="2022-10-05 10:10:30",
                    query_duration_ms=200,
                    client_query_id="111-222-333::999",
                ),
            ],
        )

        response = self.client.post(
            "/api/time_to_see_data/session_events",
            {
                "team_id": 2,
                "session_start": "2022-10-05T10:10:28Z",
                "session_end": "2022-10-05T10:30:30Z",
                "session_id": "123",
            },
        ).json()

        assert json.dumps(response, indent=4) == self.snapshot


@dataclass
class MetricsRow:
    team_events_last_month: int = 55555
    query_id: str = "123"
    primary_interaction_id: str = "456"
    team_id: int = 2
    user_id: int = 123
    session_id: str = ""
    timestamp: str = "2022-10-05 10:20:00"
    type: str = ""
    context: str = ""
    is_primary_interaction: int = True
    time_to_see_data_ms: int = 200
    status: str = ""
    api_response_bytes: int = 100
    current_url: str = ""
    api_url: str = ""
    insight: str = ""
    action: str = ""
    insights_fetched: int = 1
    insights_fetched_cached: int = 0
    min_last_refresh: str = ""
    max_last_refresh: str = ""


@dataclass
class QueryLogRow:
    host: str = ""
    timestamp: str = ""
    query_duration_ms: int = 555
    read_rows: int = 0
    read_bytes: int = 0
    result_rows: int = 0
    result_bytes: int = 0
    memory_usage: int = 0
    is_initial_query: int = 1
    exception_code: int = 0
    team_id: int = 2
    team_events_last_month: int = 0
    user_id: int = 123
    session_id: str = "123"
    kind: str = ""
    query_type: str = ""
    client_query_id: str = ""
    id: str = ""
    route_id: str = ""
    query_time_range_days: int = 1
    has_joins: int = 0
    has_json_operations: int = 0
    filter_by_type: List[str] = field(default_factory=list)
    breakdown_by: List[str] = field(default_factory=list)
    entity_math: List[str] = field(default_factory=list)
    filter: str = ""
    ProfileEvents: dict = field(default_factory=dict)
    tables: List[str] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    query: str = ""
    log_comment = ""


def insert(table: str, rows: List):
    columns = asdict(rows[0]).keys()

    all_values, params = [], {}
    for i, row in enumerate(rows):
        values = ", ".join([f"%(p_{i}_{j})s" for j, _ in enumerate(columns)])
        all_values.append(f"({values})")

        for j, column in enumerate(columns):
            params[f"p_{i}_{j}"] = getattr(row, column)

    sync_execute(
        f"""
        INSERT INTO {table} ({', '.join(columns)})
        VALUES {', '.join(all_values)}
    """,
        params,
    )
