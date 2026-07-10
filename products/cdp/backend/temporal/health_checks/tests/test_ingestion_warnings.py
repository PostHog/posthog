import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.models.health_issue import HealthIssue
from posthog.models.ingestion_warnings.sql_v2 import TABLE_NAME
from posthog.models.team import Team

from products.cdp.backend.temporal.health_checks.ingestion_warnings import IngestionWarningsCheck

INSERT_WARNINGS = f"""
INSERT INTO {TABLE_NAME} (team_id, source, type, details, timestamp, _timestamp, _offset, _partition)
SELECT %(team_id)s, %(source)s, %(type)s, %(details)s, %(timestamp)s, now(), 0, 0
FROM numbers(%(copies)s)
"""


def insert_warnings(
    team_id: int, type: str, copies: int, token: str | None = None, source: str = "plugin-server"
) -> None:
    details: dict = {"category": "event", "severity": "error"}
    if token is not None:
        details["token"] = token
    sync_execute(
        INSERT_WARNINGS,
        {
            "team_id": team_id,
            "source": source,
            "type": type,
            "details": json.dumps(details),
            "timestamp": (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
            "copies": copies,
        },
    )


class TestIngestionWarningsCheck(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        # Test teams share the fixed CONFIG_API_TOKEN while ClickHouse rows outlive
        # each test; a per-test token keeps team_id=0 capture rows isolated.
        self.team.api_token = f"phc_capture_test_{uuid4().hex}"
        self.team.save()

    def test_merges_direct_and_token_matched_rows_against_min_count(self):
        # 6 direct + 6 capture rows: each slice alone is under the min count of 10,
        # only the merged total crosses it.
        insert_warnings(self.team.id, "missing_event_name", copies=6)
        insert_warnings(0, "missing_event_name", copies=6, token=self.team.api_token, source="capture")
        # A type under the threshold even when merged must stay hidden.
        insert_warnings(0, "missing_distinct_id", copies=5, token=self.team.api_token, source="capture")

        issues = IngestionWarningsCheck().detect([self.team.id])

        assert list(issues.keys()) == [self.team.id]
        assert [(r.payload["warning_type"], r.payload["affected_count"]) for r in issues[self.team.id]] == [
            ("missing_event_name", 12)
        ]
        assert issues[self.team.id][0].severity == HealthIssue.Severity.WARNING

    def test_token_rows_of_other_teams_and_orphans_are_ignored(self):
        other_team = Team.objects.create(organization=self.organization)
        # Another team's token rows and token-less team_id=0 orphans must not
        # count toward this team, even for a type it already has.
        insert_warnings(self.team.id, "missing_event_name", copies=10)
        insert_warnings(0, "missing_event_name", copies=10, token=other_team.api_token, source="capture")
        insert_warnings(0, "missing_event_name", copies=10, source="capture")

        issues = IngestionWarningsCheck().detect([self.team.id])

        assert issues[self.team.id][0].payload["affected_count"] == 10

    def test_critical_threshold_applies_to_merged_count(self):
        # message_size_too_large escalates at 300; 200 direct + 150 capture rows
        # only cross it merged.
        insert_warnings(self.team.id, "message_size_too_large", copies=200)
        insert_warnings(0, "message_size_too_large", copies=150, token=self.team.api_token, source="capture")

        issues = IngestionWarningsCheck().detect([self.team.id])

        result = issues[self.team.id][0]
        assert result.payload["affected_count"] == 350
        assert result.severity == HealthIssue.Severity.CRITICAL
