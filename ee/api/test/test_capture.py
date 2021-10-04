import json
from typing import Any
from unittest.mock import patch

from django.test.client import Client

from posthog.test.base import APIBaseTest


def mocked_get_team_from_token(_: Any) -> None:
    raise Exception("test exception")


class TestPropertyDefinitionEnterpriseAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()

    @patch("posthog.models.Team.objects.get_team_from_token", side_effect=mocked_get_team_from_token)
    @patch("posthog.api.capture.log_event_to_dead_letter_queue")
    def test_unable_to_fetch_team(self, log_event_to_dead_letter_queue, _):
        response = self.client.post(
            "/track/",
            {
                "data": json.dumps(
                    [
                        {"event": "event1", "properties": {"distinct_id": "eeee", "token": self.team.api_token,},},
                        {"event": "event2", "properties": {"distinct_id": "aaaa", "token": self.team.api_token,},},
                    ]
                ),
                "api_key": self.team.api_token,
            },
        )

        self.assertEqual(log_event_to_dead_letter_queue.call_count, 2)

        log_event_to_dead_letter_queue_call1 = log_event_to_dead_letter_queue.call_args_list[0].args
        log_event_to_dead_letter_queue_call2 = log_event_to_dead_letter_queue.call_args_list[1].args

        self.assertEqual(type(log_event_to_dead_letter_queue_call1[0]), list)  # event
        self.assertEqual(type(log_event_to_dead_letter_queue_call2[0]), list)  # event

        self.assertEqual(log_event_to_dead_letter_queue_call1[1], "event1")  # event_name
        self.assertEqual(log_event_to_dead_letter_queue_call2[1], "event2")  # event_name

        self.assertEqual(type(log_event_to_dead_letter_queue_call1[2]), dict)  # event
        self.assertEqual(type(log_event_to_dead_letter_queue_call2[2]), dict)  # event

        self.assertEqual(
            log_event_to_dead_letter_queue_call1[3],
            "Unable to fetch team from Postgres. Error: Exception('test exception')",
        )  # error_message

        self.assertEqual(
            log_event_to_dead_letter_queue_call2[3],
            "Unable to fetch team from Postgres. Error: Exception('test exception')",
        )  # error_message

        self.assertEqual(log_event_to_dead_letter_queue_call1[4], "django_server_capture_endpoint")  # error_location
        self.assertEqual(log_event_to_dead_letter_queue_call2[4], "django_server_capture_endpoint")  # error_location
