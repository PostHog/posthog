import json
from typing import Any
from unittest.mock import patch

from django.http.request import HttpRequest
from django.test.client import Client
from rest_framework import status

from ee.kafka_client.topics import KAFKA_EVENTS_PLUGIN_INGESTION
from posthog.api.utils import determine_team_from_request_data
from posthog.test.base import APIBaseTest


def mocked_get_team_from_token(_: Any) -> None:
    raise Exception("test exception")


class TestCaptureAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()

    @patch("ee.kafka_client.client._KafkaProducer.produce")
    def test_produce_to_kafka(self, kafka_produce):
        response = self.client.post(
            "/track/",
            {
                "data": json.dumps(
                    [
                        {"event": "event1", "properties": {"distinct_id": "id1", "token": self.team.api_token,},},
                        {"event": "event2", "properties": {"distinct_id": "id2", "token": self.team.api_token,},},
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

        self.assertEquals(type(kafka_produce_call1["data"]["team_id"]), int)
        self.assertEquals(type(kafka_produce_call2["data"]["team_id"]), int)

        self.assertEquals(type(kafka_produce_call1["data"]["sent_at"]), str)
        self.assertEquals(type(kafka_produce_call2["data"]["sent_at"]), str)

        self.assertEquals(type(event1_data["properties"]), dict)
        self.assertEquals(type(event2_data["properties"]), dict)

        self.assertEquals(type(kafka_produce_call1["data"]["uuid"]), str)
        self.assertEquals(type(kafka_produce_call2["data"]["uuid"]), str)
