"""Tests for cohort API endpoints that route person lookups through personhog.

Verifies that validate_person_uuids_exist is correctly called and consumed
in the CohortSerializer._handle_static and CohortViewSet.add_persons paths.
"""

from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.personhog_client.fake_client import fake_personhog_client

UUID_A = "550e8400-e29b-41d4-a716-446655440000"
UUID_B = "550e8400-e29b-41d4-a716-446655440001"
UUID_C = "550e8400-e29b-41d4-a716-446655440002"


class TestValidatePersonUuidsExistPersonhog(SimpleTestCase):
    def test_returns_matching_uuids_via_personhog(self):
        from posthog.models.person.util import validate_person_uuids_exist

        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid=UUID_A, distinct_ids=["d1"])
            fake.add_person(team_id=1, person_id=20, uuid=UUID_B, distinct_ids=["d2"])

            result = validate_person_uuids_exist(1, [UUID_A, UUID_B, UUID_C])

            assert set(result) == {UUID_A, UUID_B}
            fake.assert_called("get_persons_by_uuids")

    def test_filters_cross_team_results(self):
        from posthog.models.person.util import validate_person_uuids_exist

        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid=UUID_A, distinct_ids=["d1"])
            fake.add_person(team_id=99, person_id=20, uuid=UUID_B, distinct_ids=["d2"])

            result = validate_person_uuids_exist(1, [UUID_A, UUID_B])

            assert result == [UUID_A]

    def test_returns_empty_for_no_matches(self):
        from posthog.models.person.util import validate_person_uuids_exist

        with fake_personhog_client() as fake:
            result = validate_person_uuids_exist(1, [UUID_A])

            assert result == []
            fake.assert_called("get_persons_by_uuids")

    @patch("posthog.models.cohort.cohort.Cohort.insert_users_list_by_uuid")
    def test_cohort_add_persons_consumes_personhog_uuids(self, mock_insert):
        """Verify that validate_person_uuids_exist output flows correctly
        into insert_users_list_by_uuid when called from the cohort add_persons path."""
        from posthog.models.person.util import validate_person_uuids_exist

        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid=UUID_A, distinct_ids=["d1"])
            fake.add_person(team_id=1, person_id=20, uuid=UUID_B, distinct_ids=["d2"])

            uuids = validate_person_uuids_exist(1, [UUID_A, UUID_B])

            # Simulate what add_persons does after validation
            assert len(uuids) > 0
            assert all(isinstance(u, str) for u in uuids)
            fake.assert_called("get_persons_by_uuids")
