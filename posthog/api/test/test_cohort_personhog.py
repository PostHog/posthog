"""Tests that cohort API endpoints produce identical results
via the personhog path."""

from posthog.test.base import APIBaseTest, BaseTest

from rest_framework import status

from posthog.models.person.util import validate_person_uuids_exist
from posthog.personhog_client.fake_client import get_active_fake
from posthog.test.persons import create_person

from products.cohorts.backend.models.cohort import Cohort


class TestValidatePersonUuidsExist(BaseTest):
    def _create_person_with_uuid(self, *, team, uuid, distinct_ids):
        return create_person(team=team, uuid=uuid, distinct_ids=distinct_ids)

    def test_returns_matching_uuids(self):
        uuid_a = "550e8400-e29b-41d4-a716-446655440000"
        uuid_b = "550e8400-e29b-41d4-a716-446655440001"
        uuid_c = "550e8400-e29b-41d4-a716-446655440002"

        self._create_person_with_uuid(team=self.team, uuid=uuid_a, distinct_ids=["d1"])
        self._create_person_with_uuid(team=self.team, uuid=uuid_b, distinct_ids=["d2"])

        result = validate_person_uuids_exist(self.team.pk, [uuid_a, uuid_b, uuid_c])

        assert set(result) == {uuid_a, uuid_b}
        get_active_fake().assert_called("get_persons_by_uuids")

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
        get_active_fake().assert_called("get_persons_by_uuids")

    def test_output_is_list_of_uuid_strings(self):
        uuid_a = "550e8400-e29b-41d4-a716-446655440000"
        uuid_b = "550e8400-e29b-41d4-a716-446655440001"

        self._create_person_with_uuid(team=self.team, uuid=uuid_a, distinct_ids=["d1"])
        self._create_person_with_uuid(team=self.team, uuid=uuid_b, distinct_ids=["d2"])

        uuids = validate_person_uuids_exist(self.team.pk, [uuid_a, uuid_b])

        assert len(uuids) > 0
        assert all(isinstance(u, str) for u in uuids)
        get_active_fake().assert_called("get_persons_by_uuids")


UUID_NONEXISTENT = "550e8400-e29b-41d4-a716-446655440099"


class TestRemovePersonFromStaticCohort(APIBaseTest):
    def test_removes_person_and_routes_through_personhog(self):
        person = create_person(team=self.team, distinct_ids=["d1"], properties={"email": "test@test.com"})
        cohort = Cohort.objects.create(team=self.team, name="static", is_static=True)
        cohort.insert_users_by_list(["d1"])

        resp = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.id}/remove_person_from_static_cohort",
            {"person_id": str(person.uuid)},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["success"] is True
        get_active_fake().assert_called("get_person_by_uuid")

    def test_returns_404_for_nonexistent_person(self):
        cohort = Cohort.objects.create(team=self.team, name="static", is_static=True)

        resp = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.id}/remove_person_from_static_cohort",
            {"person_id": UUID_NONEXISTENT},
            format="json",
        )

        assert resp.status_code == status.HTTP_404_NOT_FOUND
        get_active_fake().assert_called("get_person_by_uuid")
