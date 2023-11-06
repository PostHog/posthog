import json
from typing import Dict, List, Union
from unittest.mock import patch

from rest_framework import status

from posthog.api.kafka_inspector import KafkaConsumerRecord
from posthog.test.base import APIBaseTest


class TestKafkaInspector(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    def _to_json(self, data: Union[Dict, List]) -> str:
        return json.dumps(data)

    @patch(
        "posthog.api.kafka_inspector.get_kafka_message",
        side_effect=lambda _, __, ___: KafkaConsumerRecord("foo", 0, 0, 1650375470233, "k", "v"),
    )
    def test_fetch_message(self, _):
        response = self.client.post(
            "/api/kafka_inspector/fetch_message",
            data={"topic": "foo", "partition": 1, "offset": 0},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "key": "k",
                "offset": 0,
                "partition": 0,
                "timestamp": 1650375470233,
                "topic": "foo",
                "value": "v",
            },
        )

    def test_fetch_message_invalid_params(self):
        response = self.client.post(
            "/api/kafka_inspector/fetch_message",
            data={"topic": "foo", "partition": "1", "offset": 0},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"error": "Invalid partition."})

        response = self.client.post(
            "/api/kafka_inspector/fetch_message",
            data={"topic": 42, "partition": 1, "offset": 0},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"error": "Invalid topic."})

        response = self.client.post(
            "/api/kafka_inspector/fetch_message",
            data={"topic": "foo", "partition": 1, "offset": "0"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"error": "Invalid offset."})
