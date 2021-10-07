import json
from unittest.mock import patch

from django.http import HttpRequest
from django.http.response import JsonResponse
from rest_framework import status

from posthog.api.test.test_capture import mocked_get_team_from_token
from posthog.api.utils import determine_team_from_request_data
from posthog.test.base import BaseTest


def return_true():
    return True


class TestUtils(BaseTest):
    def test_determine_team_from_request_data(self):
        # No data at all
        team, send_events_to_dead_letter_queue, fetch_team_error, error_response = determine_team_from_request_data(
            HttpRequest(), {}, ""
        )

        self.assertEqual(team, None)
        self.assertEqual(send_events_to_dead_letter_queue, False)
        self.assertEqual(fetch_team_error, None)
        self.assertEqual(type(error_response), JsonResponse)
        self.assertEqual(error_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual("Project API key invalid" in json.loads(error_response.getvalue())["detail"], True)

        # project_id exists but is invalid: should look for a personal API key and fail
        team, send_events_to_dead_letter_queue, fetch_team_error, error_response = determine_team_from_request_data(
            HttpRequest(), {"project_id": 438483483}, ""
        )

        self.assertEqual(team, None)
        self.assertEqual(send_events_to_dead_letter_queue, False)
        self.assertEqual(fetch_team_error, None)
        self.assertEqual(type(error_response), JsonResponse)
        self.assertEqual(error_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(json.loads(error_response.getvalue())["detail"], "Invalid Personal API key.")

        # Correct token
        team, send_events_to_dead_letter_queue, fetch_team_error, error_response = determine_team_from_request_data(
            HttpRequest(), {}, self.team.api_token
        )

        self.assertEqual(team, self.team)
        self.assertEqual(send_events_to_dead_letter_queue, False)
        self.assertEqual(fetch_team_error, None)
        self.assertEqual(error_response, None)

        get_team_from_token_patcher = patch(
            "posthog.models.Team.objects.get_team_from_token", side_effect=mocked_get_team_from_token
        )
        get_team_from_token_patcher.start()

        # Postgres fetch team error
        team, send_events_to_dead_letter_queue, fetch_team_error, error_response = determine_team_from_request_data(
            HttpRequest(), {}, self.team.api_token
        )

        self.assertEqual(team, None)
        self.assertEqual(send_events_to_dead_letter_queue, False)
        self.assertEqual(fetch_team_error, None)
        self.assertEqual(error_response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

        get_team_from_token_patcher.stop()
