import hashlib
import json
from typing import Any, Tuple
from unittest.mock import patch

from django.http import HttpResponse
from django.test.client import Client
from django.utils import timezone
from kafka.errors import NoBrokersAvailable
from rest_framework import status
from posthog.settings.data_stores import KAFKA_EVENTS_PLUGIN_INGESTION
from posthog.test.base import APIBaseTest


def mocked_get_ingest_context_from_token(_: Any) -> None:
    raise Exception("test exception")


class TestCaptureAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def _send_event(self) -> HttpResponse:
        event_response = self.client.post(
            "/e/",
            data={
                "data": json.dumps(
                    [
                        {"event": "beep", "properties": {"distinct_id": "eeee", "token": self.team.api_token}},
                        {"event": "boop", "properties": {"distinct_id": "aaaa", "token": self.team.api_token}},
                    ]
                ),
                "api_key": self.team.api_token,
            },
        )

        return event_response

    def _send_session_recording_event(
        self,
        number_of_events=1,
        event_data={},
        snapshot_source=3,
        snapshot_type=1,
        session_id="abc123",
        window_id="def456",
        distinct_id="ghi789",
        timestamp=1658516991883,
    ) -> Tuple[dict, HttpResponse]:
        event = {
            "event": "$snapshot",
            "properties": {
                "$snapshot_data": {
                    "type": snapshot_type,
                    "data": {"source": snapshot_source, "data": event_data},
                    "timestamp": timestamp,
                },
                "$session_id": session_id,
                "$window_id": window_id,
                "distinct_id": distinct_id,
            },
            "offset": 1993,
        }

        capture_recording_response = self.client.post(
            "/s/", data={"data": json.dumps([event for _ in range(number_of_events)]), "api_key": self.team.api_token}
        )

        return event, capture_recording_response

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_produce_to_kafka(self, kafka_produce):
        response = self.client.post(
            "/track/",
            {
                "data": json.dumps(
                    [
                        {
                            "event": "event1",
                            "properties": {
                                "distinct_id": "id1",
                                "token": self.team.api_token,
                            },
                        },
                        {
                            "event": "event2",
                            "properties": {
                                "distinct_id": "id2",
                                "token": self.team.api_token,
                            },
                        },
                    ]
                ),
                "api_key": self.team.api_token,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(kafka_produce.call_count, 2)

        kafka_produce_call1 = kafka_produce.call_args_list[0].kwargs
        kafka_produce_call2 = kafka_produce.call_args_list[1].kwargs

        # Make sure we're producing to the correct topic
        self.assertEqual(kafka_produce_call1["topic"], KAFKA_EVENTS_PLUGIN_INGESTION)
        self.assertEqual(kafka_produce_call2["topic"], KAFKA_EVENTS_PLUGIN_INGESTION)

        # Make sure we're producing the right data
        event1_data = json.loads(kafka_produce_call1["data"]["data"])
        event2_data = json.loads(kafka_produce_call2["data"]["data"])

        self.assertEqual(event1_data["event"], "event1")
        self.assertEqual(event2_data["event"], "event2")

        self.assertEqual(event1_data["properties"]["distinct_id"], "id1")
        self.assertEqual(event2_data["properties"]["distinct_id"], "id2")

        # Make sure we're producing data correctly in the way the plugin server expects
        self.assertEquals(type(kafka_produce_call1["data"]["distinct_id"]), str)
        self.assertEquals(type(kafka_produce_call2["data"]["distinct_id"]), str)

        self.assertIn(type(kafka_produce_call1["data"]["ip"]), [str, type(None)])
        self.assertIn(type(kafka_produce_call2["data"]["ip"]), [str, type(None)])

        self.assertEquals(type(kafka_produce_call1["data"]["site_url"]), str)
        self.assertEquals(type(kafka_produce_call2["data"]["site_url"]), str)

        self.assertEquals(type(kafka_produce_call1["data"]["token"]), str)
        self.assertEquals(type(kafka_produce_call2["data"]["token"]), str)

        self.assertEquals(type(kafka_produce_call1["data"]["sent_at"]), str)
        self.assertEquals(type(kafka_produce_call2["data"]["sent_at"]), str)

        self.assertEquals(type(event1_data["properties"]), dict)
        self.assertEquals(type(event2_data["properties"]), dict)

        self.assertEquals(type(kafka_produce_call1["data"]["uuid"]), str)
        self.assertEquals(type(kafka_produce_call2["data"]["uuid"]), str)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_capture_event_with_uuid_in_payload(self, kafka_produce):
        response = self.client.post(
            "/track/",
            {
                "data": json.dumps(
                    [
                        {
                            "event": "event1",
                            "uuid": "017d37c1-f285-0000-0e8b-e02d131925dc",
                            "properties": {
                                "distinct_id": "id1",
                                "token": self.team.api_token,
                            },
                        }
                    ]
                ),
                "api_key": self.team.api_token,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        kafka_produce_call = kafka_produce.call_args_list[0].kwargs
        event_data = json.loads(kafka_produce_call["data"]["data"])

        self.assertEqual(event_data["event"], "event1")
        self.assertEqual(kafka_produce_call["data"]["uuid"], "017d37c1-f285-0000-0e8b-e02d131925dc")

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_kafka_connection_error(self, kafka_produce):
        kafka_produce.side_effect = NoBrokersAvailable()
        response = self.client.post(
            "/capture/",
            {
                "data": json.dumps(
                    [
                        {
                            "event": "event1",
                            "properties": {
                                "distinct_id": "id1",
                                "token": self.team.api_token,
                            },
                        }
                    ]
                ),
                "api_key": self.team.api_token,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(
            response.json(),
            {
                "type": "server_error",
                "code": "server_error",
                "detail": "Unable to store event. Please try again. If you are the owner of this app you can check the logs for further details.",
                "attr": None,
            },
        )

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_partition_key_override(self, kafka_produce):
        default_partition_key = f"{self.team.api_token}:id1"

        self.client.post(
            "/capture/",
            {
                "data": json.dumps(
                    [
                        {
                            "event": "event1",
                            "properties": {
                                "distinct_id": "id1",
                                "token": self.team.api_token,
                            },
                        }
                    ]
                ),
                "api_key": self.team.api_token,
            },
        )

        # By default, we use (the hash of) <team_id:distinct_id> as the partition key
        kafka_produce_call = kafka_produce.call_args_list[0].kwargs
        self.assertEqual(
            kafka_produce_call["key"],
            hashlib.sha256(default_partition_key.encode()).hexdigest(),
        )

        # Setting up an override via EVENT_PARTITION_KEYS_TO_OVERRIDE should cause us to pass None
        # as the key when producing to Kafka, leading to random partitioning
        with self.settings(EVENT_PARTITION_KEYS_TO_OVERRIDE=[default_partition_key]):
            response = self.client.post(
                "/capture/",
                {
                    "data": json.dumps(
                        [
                            {
                                "event": "event1",
                                "properties": {
                                    "distinct_id": "id1",
                                    "token": self.team.api_token,
                                },
                            }
                        ]
                    ),
                    "api_key": self.team.api_token,
                },
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            kafka_produce_call = kafka_produce.call_args_list[1].kwargs
            self.assertEqual(kafka_produce_call["key"], None)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_quota_limits_ignored_if_disabled(self, kafka_produce) -> None:
        from ee.billing.quota_limiting import QuotaResource, replace_limited_team_tokens

        replace_limited_team_tokens(QuotaResource.RECORDINGS, {self.team.api_token: timezone.now().timestamp() + 10000})
        replace_limited_team_tokens(QuotaResource.EVENTS, {self.team.api_token: timezone.now().timestamp() + 10000})
        self._send_session_recording_event()
        self.assertEqual(kafka_produce.call_count, 2)

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_quota_limits(self, kafka_produce) -> None:
        from ee.billing.quota_limiting import QuotaResource, replace_limited_team_tokens

        def _produce_events():
            kafka_produce.reset_mock()
            self._send_session_recording_event()
            self._send_event()

        with self.settings(QUOTA_LIMITING_ENABLED=True):
            replace_limited_team_tokens(QuotaResource.EVENTS, {})
            replace_limited_team_tokens(QuotaResource.RECORDINGS, {})

            _produce_events()
            self.assertEqual(kafka_produce.call_count, 4)

            replace_limited_team_tokens(QuotaResource.EVENTS, {self.team.api_token: timezone.now().timestamp() + 10000})
            _produce_events()
            self.assertEqual(kafka_produce.call_count, 2)  # Only the recording event

            replace_limited_team_tokens(
                QuotaResource.RECORDINGS, {self.team.api_token: timezone.now().timestamp() + 10000}
            )
            _produce_events()
            self.assertEqual(kafka_produce.call_count, 0)  # No events

            replace_limited_team_tokens(
                QuotaResource.RECORDINGS, {self.team.api_token: timezone.now().timestamp() - 10000}
            )
            replace_limited_team_tokens(QuotaResource.EVENTS, {self.team.api_token: timezone.now().timestamp() - 10000})
            _produce_events()
            self.assertEqual(kafka_produce.call_count, 4)  # All events as limit-until timestamp is in the past

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_quota_limited_recordings_return_retry_after_header(self, _kafka_produce) -> None:
        with self.settings(QUOTA_LIMITING_ENABLED=True):
            from ee.billing.quota_limiting import QuotaResource, replace_limited_team_tokens

            replace_limited_team_tokens(
                QuotaResource.RECORDINGS, {self.team.api_token: timezone.now().timestamp() + 10000}
            )
            _, response = self._send_session_recording_event()

            assert response.json() == {
                "status": 1,
                "quota_limited": ["recordings"],
            }

    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_quota_limiting_does_not_affect_events_body(self, _kafka_produce) -> None:
        with self.settings(QUOTA_LIMITING_ENABLED=True):
            from ee.billing.quota_limiting import QuotaResource, replace_limited_team_tokens

            replace_limited_team_tokens(QuotaResource.EVENTS, {self.team.api_token: timezone.now().timestamp() + 10000})

            response = self._send_event()

            assert response.json() == {"status": 1}
