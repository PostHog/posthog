from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

from rest_framework import status

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.hog_functions.hog_function import HogFunction


def create_log_entry(
    team_id: int,
    log_source: str,
    log_source_id: str,
    message: str,
    level: str,
    instance_id: str | None = None,
    timestamp: str | None = None,
):
    from posthog.clickhouse.log_entries import INSERT_LOG_ENTRY_SQL

    sync_execute(
        INSERT_LOG_ENTRY_SQL,
        {
            "team_id": team_id,
            "log_source": log_source,
            "log_source_id": log_source_id,
            "instance_id": instance_id,
            "timestamp": timestamp or datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "level": level,
            "message": message,
        },
    )


class TestLogEntries(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    hog_function: HogFunction

    def setUp(self):
        super().setUp()
        # Create a base hog function to use as the reference for log entries
        self.hog_function = HogFunction.objects.create(
            team=self.team,
            name="Fetch URL",
            description="Test description",
            hog="fetch(inputs.url);",
        )

    def get_log_entries(self, params=None):
        return self.client.get(f"/api/projects/{self.team.id}/hog_functions/{self.hog_function.id}/logs/", params)

    def create_log_for_function(self, level: str, instance_id="instance-id-1", message=None, timestamp=None):
        create_log_entry(
            team_id=self.team.pk,
            log_source="hog_function",
            log_source_id=str(self.hog_function.pk),
            instance_id=instance_id,
            message=message or f"Test log. Much {level}.",
            level=level,
            timestamp=timestamp,
        )

    def test_returns_default(self):
        res = self.get_log_entries()
        assert res.status_code == status.HTTP_200_OK
        assert res.json() == {
            "count": 0,
            "next": None,
            "previous": None,
            "results": [],
        }

    def test_returns_log_entries(self):
        """Test the simple case of fetching a log entry."""
        self.create_log_for_function(level="info", timestamp="2023-09-22 01:00:00")

        results = self.get_log_entries().json()["results"]

        assert results == [
            {
                "log_source_id": str(self.hog_function.pk),
                "instance_id": "instance-id-1",
                "timestamp": "2023-09-22T01:00:00Z",
                "level": "INFO",
                "message": "Test log. Much info.",
            }
        ]

    def test_filters_log_entries_by_level(self):
        """Test the simple case of fetching a log entry."""
        self.create_log_for_function(level="info")
        self.create_log_for_function(level="error")
        self.create_log_for_function(level="info")
        self.create_log_for_function(level="warn")

        results = self.get_log_entries({"level": "info,WARN"}).json()["results"]

        assert len(results) == 3
        assert results[0]["level"] == "WARN"
        assert results[1]["level"] == "INFO"
        assert results[2]["level"] == "INFO"

    def test_filters_log_entries_by_instance_id(self):
        """Test the simple case of fetching a log entry."""
        self.create_log_for_function(level="info", instance_id="instance-id-1")
        self.create_log_for_function(level="error", instance_id="instance-id-2")
        self.create_log_for_function(level="error", instance_id="instance-id-1")
        self.create_log_for_function(level="error", instance_id="instance-id-2")

        results = self.get_log_entries({"instance_id": "instance-id-1"}).json()["results"]

        assert len(results) == 2
        assert results[0]["instance_id"] == "instance-id-1"
        assert results[1]["instance_id"] == "instance-id-1"
        assert results[0]["level"] == "ERROR"
        assert results[1]["level"] == "INFO"
