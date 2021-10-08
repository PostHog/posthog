import json
from unittest.mock import patch

from django.http import HttpRequest
from django.http.response import JsonResponse
from rest_framework import status

from posthog.api.test.test_capture import mocked_get_team_from_token
from posthog.api.utils import extract_data_from_request, get_team
from posthog.test.base import BaseTest


def return_true():
    return True


class TestUtils(BaseTest):
    def test_get_team(self):
        # No data at all
        team, error_response = get_team(HttpRequest(), {}, "")

        self.assertEqual(team, None)
        self.assertEqual(type(error_response), JsonResponse)
        self.assertEqual(error_response.status_code, status.HTTP_401_UNAUTHORIZED)  # type: ignore
        self.assertEqual("Project API key invalid" in json.loads(error_response.getvalue())["detail"], True)  # type: ignore

        # project_id exists but is invalid: should look for a personal API key and fail
        team, error_response = get_team(HttpRequest(), {"project_id": 438483483}, "")

        self.assertEqual(team, None)
        self.assertEqual(type(error_response), JsonResponse)
        self.assertEqual(error_response.status_code, status.HTTP_401_UNAUTHORIZED)  # type: ignore
        self.assertEqual(json.loads(error_response.getvalue())["detail"], "Invalid Personal API key.")  # type: ignore

        # Correct token
        team, error_response = get_team(HttpRequest(), {}, self.team.api_token)

        self.assertEqual(team, self.team)
        self.assertEqual(error_response, None)

        get_team_from_token_patcher = patch(
            "posthog.models.Team.objects.get_team_from_token", side_effect=mocked_get_team_from_token
        )
        get_team_from_token_patcher.start()

        # Postgres fetch team error
        team, error_response = get_team(HttpRequest(), {}, self.team.api_token)

        self.assertEqual(team, None)
        self.assertEqual(error_response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)  # type: ignore

        get_team_from_token_patcher.stop()

    def test_extract_data_from_request(self):
        # No data in request
        data, error_response = extract_data_from_request(HttpRequest())
        self.assertEqual(data, None)
        self.assertEqual(error_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual("No data found" in json.loads(error_response.getvalue())["detail"], True)

        # Valid request with event
        request = HttpRequest()
        request.method = "POST"
        request.POST = {"data": json.dumps({"event": "some event"})}  # type: ignore
        data, error_response = extract_data_from_request(request)
        self.assertEqual(data, {"event": "some event"})
        self.assertEqual(error_response, None)
