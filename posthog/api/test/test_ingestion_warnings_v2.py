import json
from uuid import uuid4

from freezegun.api import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.models.ingestion_warnings.sql_v2 import TABLE_NAME
from posthog.models.team import Team

INSERT_INGESTION_WARNING_V2 = f"""
INSERT INTO {TABLE_NAME} (team_id, source, type, details, timestamp, _timestamp, _offset, _partition)
SELECT %(team_id)s, %(source)s, %(type)s, %(details)s, %(timestamp)s, now(), 0, 0
"""


def create_warning(team_id: int, type: str, timestamp: str, details: dict, source: str = "plugin-server") -> None:
    sync_execute(
        INSERT_INGESTION_WARNING_V2,
        {
            "team_id": team_id,
            "source": source,
            "type": type,
            "details": json.dumps(details),
            "timestamp": timestamp,
        },
    )


@freeze_time("2026-07-07T12:00:00.000Z")
class TestIngestionWarningsV2API(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        for hour_timestamp in ["2026-07-07 09:00:00", "2026-07-07 09:30:00", "2026-07-07 10:00:00"]:
            create_warning(
                team_id=self.team.id,
                type="message_size_too_large",
                timestamp=hour_timestamp,
                details={
                    "category": "size",
                    "severity": "error",
                    "pipelineStep": "emit-event-step",
                    "eventUuid": "018e0a2e-0000-0000-0000-000000000001",
                    "distinctId": "large-payload-user",
                },
            )
        create_warning(
            team_id=self.team.id,
            type="cannot_merge_already_identified",
            timestamp="2026-07-07 11:00:00",
            details={
                "category": "merge",
                "severity": "warning",
                "distinctId": "merge-user",
            },
        )
        # Outside the default 24h window
        create_warning(
            team_id=self.team.id,
            type="message_size_too_large",
            timestamp="2026-07-04 10:00:00",
            details={"category": "size", "severity": "error", "distinctId": "old-user"},
        )
        # Another team's warning must never leak
        other_team = Team.objects.create(organization=self.organization)
        create_warning(
            team_id=other_team.id,
            type="message_size_too_large",
            timestamp="2026-07-07 10:00:00",
            details={"category": "size", "severity": "error", "distinctId": "other-team-user"},
        )

    def _list(self, **params) -> tuple[int, list]:
        response = self.client.get(f"/api/projects/{self.team.pk}/ingestion_warnings_v2/", params)
        return response.status_code, response.json()

    def _use_unique_api_token(self) -> str:
        # Test teams share the fixed CONFIG_API_TOKEN while ClickHouse rows outlive
        # each test, so team_id=0 capture rows keyed by that token would leak between
        # tests. A per-test token keeps them isolated.
        self.team.api_token = f"phc_capture_test_{uuid4().hex}"
        self.team.save()
        return self.team.api_token

    def test_groups_warnings_by_type_with_counts_samples_and_sparkline(self):
        status_code, results = self._list()

        assert status_code == status.HTTP_200_OK
        assert [(r["type"], r["count"]) for r in results] == [
            ("message_size_too_large", 3),
            ("cannot_merge_already_identified", 1),
        ]

        size_warnings = results[0]
        assert size_warnings["category"] == "size"
        assert size_warnings["severity"] == "error"
        assert size_warnings["last_seen"].startswith("2026-07-07T10:00:00")

        sample_timestamps = [sample["timestamp"] for sample in size_warnings["samples"]]
        assert sample_timestamps == sorted(sample_timestamps, reverse=True)
        newest_sample = size_warnings["samples"][0]
        assert newest_sample["pipeline_step"] == "emit-event-step"
        assert newest_sample["event_uuid"] == "018e0a2e-0000-0000-0000-000000000001"
        assert newest_sample["distinct_id"] == "large-payload-user"
        assert newest_sample["details"]["distinctId"] == "large-payload-user"

        # 24h window -> hourly buckets, oldest first: two warnings at 09:xx, one at 10:00
        assert [point["count"] for point in size_warnings["sparkline"]] == [2, 1]

        merge_warnings = results[1]
        assert merge_warnings["category"] == "merge"
        assert merge_warnings["severity"] == "warning"

    @parameterized.expand(
        [
            ("category", "merge", ["cannot_merge_already_identified"]),
            ("type", "cannot_merge_already_identified", ["cannot_merge_already_identified"]),
            ("severity", "error", ["message_size_too_large"]),
            ("q", "large-payload-user", ["message_size_too_large"]),
        ]
    )
    def test_filters_narrow_results(self, param: str, value: str, expected_types: list[str]):
        status_code, results = self._list(**{param: value})

        assert status_code == status.HTTP_200_OK
        assert [r["type"] for r in results] == expected_types

    def test_time_range_bounds_results(self):
        # Default 24h window excludes the 3-day-old warning; a wider window includes it
        _, results = self._list(since="-7d", type="message_size_too_large")
        assert results[0]["count"] == 4

        # Explicit ISO bounds narrow down to a single warning
        _, results = self._list(since="2026-07-07T10:30:00Z", until="2026-07-07T11:30:00Z")
        assert [(r["type"], r["count"]) for r in results] == [("cannot_merge_already_identified", 1)]

    @parameterized.expand(
        [
            ("count", ["message_size_too_large", "cannot_merge_already_identified"]),
            ("last_seen", ["cannot_merge_already_identified", "message_size_too_large"]),
        ]
    )
    def test_order_by(self, order_by: str, expected_types: list[str]):
        status_code, results = self._list(order_by=order_by)

        assert status_code == status.HTTP_200_OK
        assert [r["type"] for r in results] == expected_types

    def test_samples_param_caps_returned_samples(self):
        for minute in range(7):
            create_warning(
                team_id=self.team.id,
                type="merge_race_condition",
                timestamp=f"2026-07-07 11:{minute:02d}:00",
                details={"category": "merge", "severity": "error"},
            )

        _, results = self._list(type="merge_race_condition")
        assert results[0]["count"] == 7
        assert len(results[0]["samples"]) == 5
        assert results[0]["samples"][0]["timestamp"].startswith("2026-07-07T11:06:00")

        _, results = self._list(type="merge_race_condition", samples=2)
        assert len(results[0]["samples"]) == 2

    @parameterized.expand(
        [
            ({"limit": 0},),
            ({"since": "2026-07-07T11:00:00Z", "until": "2026-07-07T10:00:00Z"},),
            ({"severity": "critical"},),
        ]
    )
    def test_invalid_params_return_400(self, params: dict):
        status_code, _ = self._list(**params)
        assert status_code == status.HTTP_400_BAD_REQUEST

    def test_capture_token_rows_surface_for_owning_team(self):
        token = self._use_unique_api_token()
        # Capture emits team_id=0 with the project's API token in details.
        create_warning(
            team_id=0,
            type="missing_event_name",
            timestamp="2026-07-07 11:30:00",
            details={
                "category": "event",
                "severity": "error",
                "pipelineStep": "capture_validation",
                "token": token,
                "distinctId": "capture-user",
            },
            source="capture",
        )

        status_code, results = self._list(type="missing_event_name")

        assert status_code == status.HTTP_200_OK
        assert [(r["type"], r["count"]) for r in results] == [("missing_event_name", 1)]
        sample = results[0]["samples"][0]
        assert sample["source"] == "capture"
        assert sample["pipeline_step"] == "capture_validation"
        assert sample["distinct_id"] == "capture-user"

    def test_capture_rows_merge_with_plugin_server_rows_of_same_type(self):
        token = self._use_unique_api_token()
        # setUp created 3 in-window plugin-server message_size_too_large rows; a
        # token-matched capture row of the same type must join that group.
        create_warning(
            team_id=0,
            type="message_size_too_large",
            timestamp="2026-07-07 11:45:00",
            details={"category": "size", "severity": "error", "token": token},
            source="capture",
        )

        _, results = self._list(type="message_size_too_large")

        assert results[0]["count"] == 4
        assert results[0]["samples"][0]["source"] == "capture"

    @parameterized.expand(
        [
            ("other_team_token", {"token": "phc_other_team_secret_token"}),
            ("no_token", {}),
            ("empty_token", {"token": ""}),
        ]
    )
    def test_team_zero_rows_without_matching_token_never_surface(self, _name: str, token_details: dict):
        self._use_unique_api_token()
        create_warning(
            team_id=0,
            type="missing_distinct_id",
            timestamp="2026-07-07 11:30:00",
            details={"category": "event", "severity": "error", **token_details},
            source="capture",
        )

        status_code, results = self._list(type="missing_distinct_id")

        assert status_code == status.HTTP_200_OK
        assert results == []
