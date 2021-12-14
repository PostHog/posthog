import json
from typing import Any, cast
from unittest.mock import patch

from django.http import HttpRequest
from django.http.response import JsonResponse
from django.test.client import RequestFactory
from rest_framework import status

from posthog.api.test.test_capture import mocked_get_team_from_token
from posthog.api.utils import PaginationMode, format_paginated_url, get_data, get_target_entity, get_team
from posthog.test.base import BaseTest


def return_true():
    return True


class TestUtils(BaseTest):
    def test_get_team(self):
        # No data at all
        team, db_error, error_response = get_team(HttpRequest(), {}, "")

        self.assertEqual(team, None)
        self.assertEqual(db_error, None)
        self.assertEqual(type(error_response), JsonResponse)
        self.assertEqual(error_response.status_code, status.HTTP_401_UNAUTHORIZED)  # type: ignore
        self.assertEqual("Project API key invalid" in json.loads(error_response.getvalue())["detail"], True)  # type: ignore

        # project_id exists but is invalid: should look for a personal API key and fail
        team, db_error, error_response = get_team(HttpRequest(), {"project_id": 438483483}, "")

        self.assertEqual(team, None)
        self.assertEqual(db_error, None)
        self.assertEqual(type(error_response), JsonResponse)
        self.assertEqual(error_response.status_code, status.HTTP_401_UNAUTHORIZED)  # type: ignore
        self.assertEqual(json.loads(error_response.getvalue())["detail"], "Invalid Personal API key.")  # type: ignore

        # Correct token
        team, db_error, error_response = get_team(HttpRequest(), {}, self.team.api_token)

        self.assertEqual(team, self.team)
        self.assertEqual(db_error, None)
        self.assertEqual(error_response, None)

        get_team_from_token_patcher = patch(
            "posthog.models.Team.objects.get_team_from_token", side_effect=mocked_get_team_from_token
        )
        get_team_from_token_patcher.start()

        # Postgres fetch team error
        team, db_error, error_response = get_team(HttpRequest(), {}, self.team.api_token)

        self.assertEqual(team, None)
        self.assertEqual(db_error, "Exception('test exception')")
        self.assertEqual(error_response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)  # type: ignore

        get_team_from_token_patcher.stop()

    def test_get_data(self):
        # No data in request
        data, error_response = get_data(HttpRequest())
        self.assertEqual(data, None)
        self.assertEqual(error_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual("No data found" in json.loads(error_response.getvalue())["detail"], True)

        # Valid request with event
        request = HttpRequest()
        request.method = "POST"
        request.POST = {"data": json.dumps({"event": "some event"})}  # type: ignore
        data, error_response = get_data(request)
        self.assertEqual(data, {"event": "some event"})
        self.assertEqual(error_response, None)

    def test_format_paginated_url(self):
        request = lambda url: cast(Any, RequestFactory().get(url))

        self.assertEqual(
            format_paginated_url(request("/api/some_url"), offset=0, page_size=10),
            "http://testserver/api/some_url?offset=10",
        )
        self.assertEqual(
            format_paginated_url(request("/api/some_url?offset=0"), offset=0, page_size=10), "api/some_url?offset=10"
        )
        self.assertEqual(
            format_paginated_url(
                request("/api/some_url?offset=0"), offset=0, page_size=10, mode=PaginationMode.previous
            ),
            None,
        )
        self.assertEqual(
            format_paginated_url(
                request("/api/some_url?offset=0"), offset=20, page_size=10, mode=PaginationMode.previous
            ),
            "api/some_url?offset=0",
        )

    def test_get_target_entity(self):
        request = lambda url: cast(Any, RequestFactory().get(url))
        first_request = request(
            f"/api/?entity_id=$pageview&entity_type=events&events={json.dumps([{'id': '$pageview', 'type': 'events'}])}"
        )
        entity = get_target_entity(first_request)

        assert entity.id == "$pageview"
        assert entity.type == "events"
        assert entity.math == None

        second_request = request(
            f"/api/?entity_id=$pageview&entity_type=events&entity_math=unique_group&events={json.dumps([{'id': '$pageview', 'type': 'events', 'math': 'unique_group'}, {'id': '$pageview', 'type': 'events'}])}"
        )
        entity = get_target_entity(second_request)

        assert entity.id == "$pageview"
        assert entity.type == "events"
        assert entity.math == "unique_group"
