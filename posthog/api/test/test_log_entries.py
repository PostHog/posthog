from datetime import UTC, datetime, timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.api.log_entries import count_log_entries
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.cdp.backend.facade.clickhouse import INSERT_HOG_INVOCATION_RESULT_SQL
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.event_definitions.backend.models import PropertyDefinition


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

    def _set_property_access(self, property_type: int, access: str) -> None:
        self.organization.available_product_features = (
            []
            if access == "feature_disabled"
            else [
                {"key": feature, "name": feature}
                for feature in [AvailableFeature.PROPERTY_ACCESS_CONTROL, AvailableFeature.ROLE_BASED_ACCESS]
            ]
        )
        self.organization.save()
        self.organization_membership.level = (
            OrganizationMembership.Level.ADMIN if access == "admin" else OrganizationMembership.Level.MEMBER
        )
        self.organization_membership.save()
        property_definition = PropertyDefinition.objects.create(
            team=self.team,
            name="private_note",
            type=property_type,
            group_type_index=0 if property_type == PropertyDefinition.Type.GROUP else None,
        )
        PropertyAccessControl.objects.create(
            team=self.team, property_definition=property_definition, access_level="none"
        )
        if access == "granted":
            PropertyAccessControl.objects.create(
                team=self.team,
                property_definition=property_definition,
                organization_member=self.organization_membership,
                access_level="read",
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

    @time_machine.travel("2023-09-23 12:00:00", tick=False)
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

    @parameterized.expand(
        [
            ("event", PropertyDefinition.Type.EVENT, "restricted", "log_entries"),
            ("person", PropertyDefinition.Type.PERSON, "restricted", "log_entries"),
            ("group", PropertyDefinition.Type.GROUP, "restricted", "log_entries"),
            ("member_override", PropertyDefinition.Type.EVENT, "granted", "log_entries"),
            ("admin", PropertyDefinition.Type.EVENT, "admin", "log_entries"),
            ("feature_disabled", PropertyDefinition.Type.EVENT, "feature_disabled", "log_entries"),
            ("alias", PropertyDefinition.Type.EVENT, "restricted", "log_entries AS logs"),
            ("subquery", PropertyDefinition.Type.EVENT, "restricted", "(SELECT * FROM log_entries)"),
        ]
    )
    def test_hogql_log_entries_follow_property_access(
        self, _name: str, property_type: int, access: str, source: str
    ) -> None:
        self._set_property_access(property_type, access)
        sources = ["batch_export", "hog_flow", "hog_function", "plugin", "session_replay"]
        for log_source in sources:
            create_log_entry(
                team_id=self.team.pk,
                log_source=log_source,
                log_source_id=str(self.hog_function.pk),
                instance_id="test-instance",
                message=f"{log_source} log message",
                level="info",
            )

        response = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"SELECT log_source, message FROM {source} ORDER BY log_source",
                },
                "refresh": "force_blocking",
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        expected_sources = ["batch_export", "session_replay"] if access == "restricted" else sources
        assert response.json()["results"] == [
            [log_source, f"{log_source} log message"] for log_source in expected_sources
        ]

    @parameterized.expand([("restricted",), ("admin",)])
    @time_machine.travel("2026-01-15 12:00:00", tick=False)
    def test_hogql_invocation_errors_follow_property_access(self, access: str) -> None:
        self._set_property_access(PropertyDefinition.Type.EVENT, access)
        now = datetime(2026, 1, 15, 12, tzinfo=UTC)
        kinds = ["hog_flow", "hog_flow_rerun", "hog_function", "hog_function_rerun"]
        for kind in kinds:
            sync_execute(
                INSERT_HOG_INVOCATION_RESULT_SQL,
                {
                    "team_id": self.team.pk,
                    "function_kind": kind,
                    "function_id": str(self.hog_function.pk),
                    "invocation_id": kind,
                    "parent_run_id": "",
                    "status": "failed",
                    "attempts": 1,
                    "is_retry": 0,
                    "scheduled_at": now,
                    "first_scheduled_at": now,
                    "started_at": now,
                    "finished_at": now,
                    "duration_ms": 1,
                    "error_kind": "Error",
                    "error_message": f"{kind} error message",
                    "event_uuid": "",
                    "distinct_id": "",
                    "person_id": "",
                    "invocation_globals": "{}",
                    "version": 1,
                    "is_deleted": 0,
                },
                workload=Workload.OFFLINE,
            )

        response = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": "SELECT function_kind, error_message FROM posthog.hog_invocation_results ORDER BY function_kind",
                },
                "refresh": "force_blocking",
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        expected_kinds = [] if access == "restricted" else kinds
        assert response.json()["results"] == [[kind, f"{kind} error message"] for kind in expected_kinds]

    @parameterized.expand([("restricted",), ("member_rule",), ("admin",), ("granted",)])
    @time_machine.travel("2026-11-01 12:00:00", tick=False)
    def test_mirrored_pipeline_logs_follow_property_access(self, access: str) -> None:
        self._set_property_access(PropertyDefinition.Type.EVENT, access)
        if access == "member_rule":
            PropertyAccessControl.objects.filter(team=self.team).update(
                organization_member=self.organization_membership
            )
        services = ["application", "posthog-internal-hog-functions", "posthog-internal-workflows"]
        for service in services:
            sync_execute(
                """INSERT INTO logs
                (uuid, team_id, timestamp, observed_timestamp, body, severity_text, severity_number, service_name, attributes_map_str)
                VALUES (%(uuid)s, %(team_id)s, %(timestamp)s, %(timestamp)s, %(body)s, 'info', 9, %(service)s, %(attributes)s)""",
                {
                    "uuid": str(uuid4()),
                    "team_id": self.team.pk,
                    "timestamp": datetime(2026, 11, 1, 11, tzinfo=UTC),
                    "body": f"{service} message",
                    "service": service,
                    "attributes": {"permission_note__str": service},
                },
                workload=Workload.LOGS,
            )
        expected_services = ["application"] if access in {"restricted", "member_rule"} else services

        hogql = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            {
                "query": {"kind": "HogQLQuery", "query": "SELECT service_name, body FROM logs ORDER BY service_name"},
                "refresh": "force_blocking",
            },
        )
        assert hogql.status_code == 200, hogql.json()
        assert hogql.json()["results"] == [[service, f"{service} message"] for service in expected_services]

        logs = self.client.post(
            f"/api/projects/{self.team.pk}/logs/query/",
            {"query": {"dateRange": {"date_from": "-1d"}, "limit": 100}},
        )
        assert logs.status_code == 200, logs.json()
        assert sorted(row["body"] for row in logs.json()["results"]) == [
            f"{service} message" for service in expected_services
        ]

        groups = self.client.post(
            f"/api/projects/{self.team.pk}/logs/group-by/",
            {"query": {"dateRange": {"date_from": "-1d"}, "groupBy": "permission_note"}},
        )
        assert groups.status_code == 200, groups.json()
        assert sorted(row["value"] for row in groups.json()["groups"]) == expected_services

        attributes = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": "SELECT DISTINCT service_name, attribute_value FROM log_attributes ORDER BY service_name",
                },
                "refresh": "force_blocking",
            },
        )
        assert attributes.status_code == 200, attributes.json()
        assert attributes.json()["results"] == [[service, service] for service in expected_services]

    @time_machine.travel("2023-09-23 12:00:00", tick=False)
    def test_pages_log_entries_by_offset(self):
        for hour in range(1, 4):
            self.create_log_for_function(level="info", message=f"entry {hour}", timestamp=f"2023-09-22 0{hour}:00:00")

        first_page = self.get_log_entries({"limit": 2}).json()
        with patch("posthog.api.log_entries.count_log_entries", wraps=count_log_entries) as count_query:
            second_page = self.get_log_entries({"limit": 2, "offset": 2}).json()
        past_the_end = self.get_log_entries({"limit": 2, "offset": 5}).json()

        assert first_page["count"] == 3
        assert [entry["message"] for entry in first_page["results"]] == ["entry 3", "entry 2"]
        assert first_page["next"] is not None
        assert second_page["count"] == 3
        assert [entry["message"] for entry in second_page["results"]] == ["entry 1"]
        assert second_page["next"] is None
        count_query.assert_not_called()
        assert past_the_end["count"] == 3
        assert past_the_end["results"] == []

    def test_default_lookback_excludes_old_entries(self):
        """Without an explicit `after`, only entries within the default lookback window are returned."""
        old_timestamp = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S.%f")
        self.create_log_for_function(level="info", message="recent log")
        self.create_log_for_function(level="info", message="old log", timestamp=old_timestamp)

        results = self.get_log_entries().json()["results"]

        assert len(results) == 1
        assert results[0]["message"] == "recent log"

    def test_explicit_after_reads_past_default_lookback(self):
        """Passing `after` explicitly overrides the default lookback window."""
        old_timestamp = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S.%f")
        self.create_log_for_function(level="info", message="recent log")
        self.create_log_for_function(level="info", message="old log", timestamp=old_timestamp)

        after = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        results = self.get_log_entries({"after": after}).json()["results"]

        assert len(results) == 2

    def test_historical_before_anchors_default_lookback(self):
        """A `before` older than the default lookback anchors the window instead of producing an impossible interval."""
        old_timestamp = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S.%f")
        self.create_log_for_function(level="info", message="recent log")
        self.create_log_for_function(level="info", message="old log", timestamp=old_timestamp)

        before = (datetime.now(UTC) - timedelta(days=29)).isoformat()
        results = self.get_log_entries({"before": before}).json()["results"]

        assert len(results) == 1
        assert results[0]["message"] == "old log"

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
