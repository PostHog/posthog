"""Tests that validate_person_uuids_exist produces identical results
via the ORM and personhog paths."""

from posthog.test.base import BaseTest

from parameterized import parameterized_class

from posthog.models.person import Person
from posthog.models.person.util import validate_person_uuids_exist
from posthog.personhog_client.test_helpers import PersonhogTestMixin


@parameterized_class(("personhog",), [(False,), (True,)])
class TestValidatePersonUuidsExist(PersonhogTestMixin, BaseTest):
    def _create_person_with_uuid(self, *, team, uuid, distinct_ids):
        """Create a person in the DB (and fake client when personhog is active)."""
        person = Person.objects.create(team=team, uuid=uuid, distinct_ids=distinct_ids)
        if self._fake_client is not None:
            self._fake_client.add_person(
                team_id=team.pk,
                person_id=person.pk,
                uuid=str(person.uuid),
                distinct_ids=distinct_ids,
            )
        return person

    def test_returns_matching_uuids(self):
        uuid_a = "550e8400-e29b-41d4-a716-446655440000"
        uuid_b = "550e8400-e29b-41d4-a716-446655440001"
        uuid_c = "550e8400-e29b-41d4-a716-446655440002"

        self._create_person_with_uuid(team=self.team, uuid=uuid_a, distinct_ids=["d1"])
        self._create_person_with_uuid(team=self.team, uuid=uuid_b, distinct_ids=["d2"])

        result = validate_person_uuids_exist(self.team.pk, [uuid_a, uuid_b, uuid_c])

        assert set(result) == {uuid_a, uuid_b}
        self._assert_personhog_called("get_persons_by_uuids")

    def test_filters_cross_team_results(self):
        uuid_a = "550e8400-e29b-41d4-a716-446655440000"
        uuid_b = "550e8400-e29b-41d4-a716-446655440001"

        other_team = self.organization.teams.create(name="Other Team")

        self._create_person_with_uuid(team=self.team, uuid=uuid_a, distinct_ids=["d1"])
        self._create_person_with_uuid(team=other_team, uuid=uuid_b, distinct_ids=["d2"])

        result = validate_person_uuids_exist(self.team.pk, [uuid_a, uuid_b])

        assert result == [uuid_a]

    def test_returns_empty_for_no_matches(self):
        uuid_missing = "550e8400-e29b-41d4-a716-446655440000"

        result = validate_person_uuids_exist(self.team.pk, [uuid_missing])

        assert result == []
        self._assert_personhog_called("get_persons_by_uuids")

    def test_output_is_list_of_uuid_strings(self):
        uuid_a = "550e8400-e29b-41d4-a716-446655440000"
        uuid_b = "550e8400-e29b-41d4-a716-446655440001"

        self._create_person_with_uuid(team=self.team, uuid=uuid_a, distinct_ids=["d1"])
        self._create_person_with_uuid(team=self.team, uuid=uuid_b, distinct_ids=["d2"])

        uuids = validate_person_uuids_exist(self.team.pk, [uuid_a, uuid_b])

        assert len(uuids) > 0
        assert all(isinstance(u, str) for u in uuids)
        self._assert_personhog_called("get_persons_by_uuids")
