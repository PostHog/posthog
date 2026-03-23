"""Tests for personhog person routing in parse_request_params."""

from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest

from posthog.models import Person
from posthog.models.event.query_event_list import parse_request_params
from posthog.personhog_client.fake_client import fake_personhog_client

UUID_A = "550e8400-e29b-41d4-a716-446655440000"


class TestParseRequestParamsPersonhog(BaseTest):
    def test_uuid_person_id_routes_through_personhog(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.pk,
                person_id=42,
                uuid=UUID_A,
                distinct_ids=["id1", "id2"],
            )

            _result, params = parse_request_params({"person_id": UUID_A}, self.team, ZoneInfo("UTC"))

            assert set(params["distinct_ids"]) == {"id1", "id2"}
            fake.assert_called("get_person_by_uuid")
            fake.assert_called("get_distinct_ids_for_person")

    def test_uuid_person_id_not_found_returns_empty(self):
        with fake_personhog_client() as fake:
            _result, params = parse_request_params({"person_id": UUID_A}, self.team, ZoneInfo("UTC"))

            assert params["distinct_ids"] == []
            fake.assert_called("get_person_by_uuid")

    def test_non_uuid_person_id_falls_back_to_orm(self):
        person = Person.objects.create(team=self.team, distinct_ids=["id1", "id2"])

        with fake_personhog_client() as fake:
            _result, params = parse_request_params({"person_id": str(person.pk)}, self.team, ZoneInfo("UTC"))

            assert set(params["distinct_ids"]) == {"id1", "id2"}
            fake.assert_not_called("get_person_by_uuid")
