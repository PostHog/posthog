"""Tests that person-related helpers in the cohort API produce identical
results via the ORM and personhog paths."""

import uuid as uuid_mod

from posthog.test.base import BaseTest

from parameterized import parameterized_class

from posthog.api.cohort import _get_person_uuid_by_uuid
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


@parameterized_class(("personhog",), [(False,), (True,)])
class TestGetPersonUuidByUuid(PersonhogTestMixin, BaseTest):
    def _create_person_with_uuid(self, *, team, person_uuid, distinct_ids):
        person = Person.objects.create(team=team, uuid=person_uuid, distinct_ids=distinct_ids)
        if self._fake_client is not None:
            self._fake_client.add_person(
                team_id=team.pk,
                person_id=person.pk,
                uuid=str(person.uuid),
                distinct_ids=distinct_ids,
            )
        return person

    def test_returns_uuid_when_person_exists(self):
        person_uuid = "550e8400-e29b-41d4-a716-446655440000"
        self._create_person_with_uuid(team=self.team, person_uuid=person_uuid, distinct_ids=["d1"])

        result = _get_person_uuid_by_uuid(self.team.pk, person_uuid)

        assert result is not None
        assert str(result) == person_uuid
        assert isinstance(result, uuid_mod.UUID)
        self._assert_personhog_called("get_person_by_uuid")

    def test_returns_none_when_person_does_not_exist(self):
        result = _get_person_uuid_by_uuid(self.team.pk, "550e8400-e29b-41d4-a716-446655440099")

        assert result is None
        self._assert_personhog_called("get_person_by_uuid")

    def test_returns_none_for_wrong_team(self):
        person_uuid = "550e8400-e29b-41d4-a716-446655440000"
        other_team = self.organization.teams.create(name="Other Team")
        self._create_person_with_uuid(team=other_team, person_uuid=person_uuid, distinct_ids=["d1"])

        result = _get_person_uuid_by_uuid(self.team.pk, person_uuid)

        assert result is None
