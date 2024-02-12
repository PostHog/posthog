import json
from typing import Dict

from freezegun.api import freeze_time
from rest_framework import status

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_INGESTION_WARNINGS
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.models.ingestion_warnings.sql import INSERT_INGESTION_WARNING
from posthog.models.organization import Organization
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from posthog.utils import cast_timestamp_or_now


def create_ingestion_warning(team_id: int, type: str, details: Dict, timestamp: str, source=""):
    timestamp = cast_timestamp_or_now(timestamp)
    data = {
        "team_id": team_id,
        "type": type,
        "source": source,
        "details": json.dumps(details),
        "timestamp": format_clickhouse_timestamp(timestamp),
        "_timestamp": format_clickhouse_timestamp(timestamp),
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_INGESTION_WARNINGS, sql=INSERT_INGESTION_WARNING, data=data)


class TestIngestionWarningsAPI(ClickhouseTestMixin, APIBaseTest):
    @freeze_time("2021-12-04T19:20:00Z")
    def test_ingestion_warnings_api(self):
        create_ingestion_warning(
            team_id=self.team.id,
            type="cannot_merge_already_identified",
            details={
                "sourcePerson": "x-uuid",
                "sourcePersonDistinctId": "Alice",
                "targetPerson": "y-uuid",
                "targetPersonDistinctId": "Bob",
            },
            timestamp="2021-12-03T00:00:00Z",
        )
        create_ingestion_warning(
            team_id=self.team.id,
            type="cannot_merge_already_identified",
            details={},
            timestamp="2021-12-02T00:00:00Z",
        )
        create_ingestion_warning(
            team_id=self.team.id,
            type="another_type",
            details={},
            timestamp="2021-11-15T00:00:00Z",
        )
        create_ingestion_warning(
            team_id=self.team.id,
            type="too_old",
            details={},
            timestamp="2021-11-01T00:00:00Z",
        )

        team2 = Organization.objects.bootstrap(None)[2]
        create_ingestion_warning(
            team_id=team2.id,
            type="too_old",
            details={},
            timestamp="2021-12-01T00:00:00Z",
        )

        response = self.client.get(f"/api/projects/{self.team.pk}/ingestion_warnings")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "results": [
                    {
                        "type": "cannot_merge_already_identified",
                        "lastSeen": "2021-12-03T00:00:00Z",
                        "warnings": [
                            {
                                "type": "cannot_merge_already_identified",
                                "timestamp": "2021-12-03T00:00:00Z",
                                "details": {
                                    "sourcePerson": "x-uuid",
                                    "sourcePersonDistinctId": "Alice",
                                    "targetPerson": "y-uuid",
                                    "targetPersonDistinctId": "Bob",
                                },
                            },
                            {
                                "type": "cannot_merge_already_identified",
                                "timestamp": "2021-12-02T00:00:00Z",
                                "details": {},
                            },
                        ],
                        "count": 2,
                    },
                    {
                        "type": "another_type",
                        "lastSeen": "2021-11-15T00:00:00Z",
                        "warnings": [
                            {
                                "type": "another_type",
                                "timestamp": "2021-11-15T00:00:00Z",
                                "details": {},
                            }
                        ],
                        "count": 1,
                    },
                ]
            },
        )
