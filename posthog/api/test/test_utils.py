import json
from typing import Any, cast
from unittest.mock import patch

from django.http import HttpRequest
from django.http.response import JsonResponse
from django.test.client import RequestFactory
from rest_framework import status

from posthog.api.test.test_capture import mocked_get_ingest_context_from_token
from posthog.api.utils import (
    EventIngestionContext,
    PaginationMode,
    check_definition_ids_inclusion_field_sql,
    format_paginated_url,
    get_data,
    get_event_ingestion_context,
    get_target_entity,
)
from posthog.models.filters.filter import Filter
from posthog.test.base import BaseTest


def return_true():
    return True


class TestUtils(BaseTest):
    def test_get_team(self):
        # No data at all
        ingestion_context, db_error, error_response = get_event_ingestion_context(HttpRequest(), {}, "")

        self.assertEqual(ingestion_context, None)
        self.assertEqual(db_error, None)
        self.assertEqual(type(error_response), JsonResponse)
        self.assertEqual(error_response.status_code, status.HTTP_401_UNAUTHORIZED)  # type: ignore
        self.assertEqual("Project API key invalid" in json.loads(error_response.getvalue())["detail"], True)  # type: ignore

        # project_id exists but is invalid: should look for a personal API key and fail
        ingestion_context, db_error, error_response = get_event_ingestion_context(
            HttpRequest(), {"project_id": 438483483}, ""
        )

        self.assertEqual(ingestion_context, None)
        self.assertEqual(db_error, None)
        self.assertEqual(type(error_response), JsonResponse)
        self.assertEqual(error_response.status_code, status.HTTP_401_UNAUTHORIZED)  # type: ignore
        self.assertEqual(json.loads(error_response.getvalue())["detail"], "Invalid Personal API key.")  # type: ignore

        # Correct token
        ingestion_context, db_error, error_response = get_event_ingestion_context(
            HttpRequest(), {}, self.team.api_token
        )

        self.assertEqual(ingestion_context, EventIngestionContext(team_id=self.team.pk, anonymize_ips=False))
        self.assertEqual(db_error, None)
        self.assertEqual(error_response, None)

        get_team_from_token_patcher = patch(
            "posthog.api.utils.get_event_ingestion_context_for_token", side_effect=mocked_get_ingest_context_from_token
        )
        get_team_from_token_patcher.start()

        # Postgres fetch team error
        ingestion_context, db_error, error_response = get_event_ingestion_context(
            HttpRequest(), {}, self.team.api_token
        )

        self.assertEqual(ingestion_context, None)
        self.assertEqual(db_error, "Exception('test exception')")
        self.assertEqual(error_response, None)

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
        filter = Filter(
            data={"entity_id": "$pageview", "entity_type": "events", "events": [{"id": "$pageview", "type": "events"}],}
        )
        entity = get_target_entity(filter)

        assert entity.id == "$pageview"
        assert entity.type == "events"
        assert entity.math is None

        filter = Filter(
            data={
                "entity_id": "$pageview",
                "entity_type": "events",
                "entity_math": "unique_group",
                "events": [
                    {"id": "$pageview", "type": "events", "math": "unique_group"},
                    {"id": "$pageview", "type": "events"},
                ],
            }
        )
        entity = get_target_entity(filter)

        assert entity.id == "$pageview"
        assert entity.type == "events"
        assert entity.math == "unique_group"

    def test_check_definition_ids_inclusion_field_sql(self):

        definition_ids = [
            "",
            None,
            '["1fcefbef-7ea1-42fd-abca-4848b53133c0", "c8452399-8a10-4142-864d-6f2ca8c65154"]',
        ]

        expected_ids_list = [[], [], ["1fcefbef-7ea1-42fd-abca-4848b53133c0", "c8452399-8a10-4142-864d-6f2ca8c65154"]]

        for raw_ids, expected_ids in zip(definition_ids, expected_ids_list):
            ordered_expected_ids = list(set(expected_ids))  # type: ignore
            # Property
            query, ids = check_definition_ids_inclusion_field_sql(raw_ids, True, "named_key")
            assert query == "(posthog_{table}.id = ANY (%(named_key)s::uuid[]))".format(table="propertydefinition",)
            assert ids == ordered_expected_ids

            # Event
            query, ids = check_definition_ids_inclusion_field_sql(raw_ids, False, "named_key")
            assert query == "(posthog_{table}.id = ANY (%(named_key)s::uuid[]))".format(table="eventdefinition")
            assert ids == ordered_expected_ids
