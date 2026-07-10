import json

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models.ingestion_warnings.sql_v2 import TABLE_NAME

INSERT_WARNING = f"""
INSERT INTO {TABLE_NAME} (team_id, source, type, details, timestamp, _timestamp, _offset, _partition)
SELECT %(team_id)s, %(source)s, %(type)s, %(details)s, %(timestamp)s, now(), 0, 0
"""


class TestIngestionWarningsV2TokenColumn(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            (
                "capture_shaped_row_materializes_token",
                0,
                "capture",
                {"token": "phc_test_token", "category": "event", "severity": "error", "count": 3},
                "phc_test_token",
            ),
            (
                "node_shaped_row_without_token_reads_empty",
                42,
                "plugin-server",
                {"category": "size", "severity": "error", "distinctId": "user-1"},
                "",
            ),
        ]
    )
    def test_token_column_derivation(
        self, _name: str, team_id: int, source: str, details: dict, expected_token: str
    ) -> None:
        warning_type = f"type_{_name}"
        sync_execute(
            INSERT_WARNING,
            {
                "team_id": team_id,
                "source": source,
                "type": warning_type,
                "details": json.dumps(details),
                "timestamp": "2026-07-10 12:00:00",
            },
        )

        rows = sync_execute(
            f"SELECT token, category, severity FROM {TABLE_NAME} WHERE type = %(type)s",
            {"type": warning_type},
        )
        assert rows == [(expected_token, details["category"], details["severity"])]
