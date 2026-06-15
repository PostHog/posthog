"""Tests that cohort API endpoints produce identical results
via the ORM and personhog paths."""

from posthog.test.base import APIBaseTest, BaseTest

from parameterized import parameterized_class
from rest_framework import status

from posthog.models.person import Person
from posthog.models.person.util import validate_person_uuids_exist
from posthog.personhog_client.test_helpers import PersonhogTestMixin

from products.cohorts.backend.models.cohort import Cohort


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


UUID_NONEXISTENT = "550e8400-e29b-41d4-a716-446655440099"


@parameterized_class(("personhog",), [(False,), (True,)])
class TestRemovePersonFromStaticCohort(PersonhogTestMixin, APIBaseTest):
    def test_removes_person_and_routes_through_personhog(self):
        person = self._seed_person(team=self.team, distinct_ids=["d1"], properties={"email": "test@test.com"})
        cohort = Cohort.objects.create(team=self.team, name="static", is_static=True)
        cohort.insert_users_by_list(["d1"])

        resp = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.id}/remove_person_from_static_cohort",
            {"person_id": str(person.uuid)},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["success"] is True
        self._assert_personhog_called("get_person_by_uuid")

    def test_returns_404_for_nonexistent_person(self):
        cohort = Cohort.objects.create(team=self.team, name="static", is_static=True)

        resp = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.id}/remove_person_from_static_cohort",
            {"person_id": UUID_NONEXISTENT},
            format="json",
        )

        assert resp.status_code == status.HTTP_404_NOT_FOUND
        self._assert_personhog_called("get_person_by_uuid")
