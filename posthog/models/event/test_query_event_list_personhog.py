"""Tests that parse_request_params person lookups produce identical results
via the ORM and personhog paths."""

from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest

from parameterized import parameterized_class

from posthog.models.event.query_event_list import parse_request_params
from posthog.personhog_client.test_helpers import PersonhogTestMixin

UUID_NONEXISTENT = "550e8400-e29b-41d4-a716-446655440000"


@parameterized_class(("personhog",), [(False,), (True,)])
class TestParseRequestParamsPersonRouting(PersonhogTestMixin, BaseTest):
    def test_uuid_person_id_resolves_distinct_ids(self):
        person = self._seed_person(team=self.team, distinct_ids=["id1", "id2"])

        _result, params = parse_request_params({"person_id": str(person.uuid)}, self.team, ZoneInfo("UTC"))

        assert set(params["distinct_ids"]) == {"id1", "id2"}
        self._assert_personhog_called("get_person_by_uuid")
        self._assert_personhog_called("get_distinct_ids_for_person")

    def test_uuid_person_id_not_found_returns_empty(self):
        _result, params = parse_request_params({"person_id": UUID_NONEXISTENT}, self.team, ZoneInfo("UTC"))

        assert params["distinct_ids"] == []
        self._assert_personhog_called("get_person_by_uuid")

    def test_integer_person_id_resolves_distinct_ids(self):
        person = self._seed_person(team=self.team, distinct_ids=["id1", "id2"])

        _result, params = parse_request_params({"person_id": str(person.pk)}, self.team, ZoneInfo("UTC"))

        assert set(params["distinct_ids"]) == {"id1", "id2"}
        self._assert_personhog_not_called("get_person_by_uuid")
        self._assert_personhog_called("get_person")
