"""Tests that parse_request_params person lookups produce identical results."""

from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest

from posthog.models.event.query_event_list import parse_request_params
from posthog.models.person import Person

UUID_NONEXISTENT = "550e8400-e29b-41d4-a716-446655440000"


class TestParseRequestParamsPersonRouting(BaseTest):
    def test_uuid_person_id_resolves_distinct_ids(self):
        person = Person.objects.create(team=self.team, distinct_ids=["id1", "id2"])

        _result, params = parse_request_params({"person_id": str(person.uuid)}, self.team, ZoneInfo("UTC"))

        assert set(params["distinct_ids"]) == {"id1", "id2"}

    def test_uuid_person_id_not_found_returns_empty(self):
        _result, params = parse_request_params({"person_id": UUID_NONEXISTENT}, self.team, ZoneInfo("UTC"))

        assert params["distinct_ids"] == []

    def test_integer_person_id_resolves_distinct_ids(self):
        person = Person.objects.create(team=self.team, distinct_ids=["id1", "id2"])

        _result, params = parse_request_params({"person_id": str(person.pk)}, self.team, ZoneInfo("UTC"))

        assert set(params["distinct_ids"]) == {"id1", "id2"}
