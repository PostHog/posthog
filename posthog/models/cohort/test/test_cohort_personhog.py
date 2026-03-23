from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.models import Cohort, Person, Team
from posthog.models.cohort.cohort import CohortPeople
from posthog.personhog_client.fake_client import fake_personhog_client

UUID_A = "00000000-0000-0000-0000-00000000000a"
UUID_B = "00000000-0000-0000-0000-00000000000b"
UUID_C = "00000000-0000-0000-0000-00000000000c"
UUID_D = "00000000-0000-0000-0000-00000000000d"
UUID_E = "00000000-0000-0000-0000-00000000000e"


class TestGetUuidsForDistinctIdsBatchPersonhog(SimpleTestCase):
    """Tests for the personhog path in Cohort._get_uuids_for_distinct_ids_batch."""

    def _make_cohort(self) -> Cohort:
        return Cohort(id=99, team_id=1)

    def test_returns_uuids_for_matching_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid=UUID_A, distinct_ids=["d1", "d2"])
            fake.add_person(team_id=1, person_id=20, uuid=UUID_B, distinct_ids=["d3"])

            cohort = self._make_cohort()
            result = cohort._get_uuids_for_distinct_ids_batch(["d1", "d3"], team_id=1)

            assert set(result) == {UUID_A, UUID_B}
            fake.assert_called("get_persons_by_distinct_ids_in_team")

    def test_returns_empty_list_for_empty_input(self):
        with fake_personhog_client() as fake:
            cohort = self._make_cohort()
            result = cohort._get_uuids_for_distinct_ids_batch([], team_id=1)

            assert result == []
            fake.assert_not_called("get_persons_by_distinct_ids_in_team")

    def test_returns_empty_list_when_no_persons_match(self):
        with fake_personhog_client():
            cohort = self._make_cohort()
            result = cohort._get_uuids_for_distinct_ids_batch(["nonexistent"], team_id=1)

            assert result == []

    def test_cross_team_isolation(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=2, person_id=10, uuid=UUID_A, distinct_ids=["d1"])

            cohort = self._make_cohort()
            result = cohort._get_uuids_for_distinct_ids_batch(["d1"], team_id=1)

            assert result == []

    def test_deduplicates_persons_with_multiple_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid=UUID_A, distinct_ids=["d1", "d2", "d3"])

            cohort = self._make_cohort()
            result = cohort._get_uuids_for_distinct_ids_batch(["d1", "d2", "d3"], team_id=1)

            # All three distinct_ids belong to the same person — should produce one UUID
            assert result == [UUID_A]

    def test_handles_mix_of_found_and_missing_distinct_ids(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=10, uuid=UUID_A, distinct_ids=["exists"])

            cohort = self._make_cohort()
            result = cohort._get_uuids_for_distinct_ids_batch(["exists", "missing1", "missing2"], team_id=1)

            assert result == [UUID_A]

    def test_multiple_persons_each_with_single_distinct_id(self):
        uuids = [UUID_A, UUID_B, UUID_C, UUID_D, UUID_E]
        with fake_personhog_client() as fake:
            for i in range(5):
                fake.add_person(
                    team_id=1,
                    person_id=i + 1,
                    uuid=uuids[i],
                    distinct_ids=[f"d{i}"],
                )

            cohort = self._make_cohort()
            result = cohort._get_uuids_for_distinct_ids_batch([f"d{i}" for i in range(5)], team_id=1)

            assert set(result) == set(uuids)

    def test_falls_back_to_orm_when_personhog_disabled(self):
        with fake_personhog_client(gate_enabled=False) as fake:
            fake.add_person(team_id=1, person_id=10, uuid=UUID_A, distinct_ids=["d1"])

            cohort = self._make_cohort()

            # With gate disabled, personhog is never called, so it falls through
            # to the ORM path. In a SimpleTestCase there is no DB, so we patch the
            # ORM path to verify the fallback is taken.
            with patch("posthog.models.person.PersonDistinctId.objects") as mock_pdi_objects:
                mock_manager = mock_pdi_objects.db_manager.return_value
                mock_manager.filter.return_value.values_list.return_value.distinct.return_value = [42]

                with patch("posthog.models.person.Person.objects") as mock_person_objects:
                    mock_p_manager = mock_person_objects.db_manager.return_value
                    mock_p_manager.filter.return_value.values_list.return_value = ["orm-uuid"]

                    result = cohort._get_uuids_for_distinct_ids_batch(["d1"], team_id=1)

            assert result == ["orm-uuid"]
            fake.assert_not_called("get_persons_by_distinct_ids_in_team")


class TestRemoveUserByUuidPersonhog(BaseTest):
    """Tests for the personhog path in Cohort.remove_user_by_uuid.

    Uses BaseTest because remove_user_by_uuid writes to the database
    (CohortPeople, cohort count) and calls ClickHouse removal.
    """

    CLASS_DATA_LEVEL_SETUP = False

    def _create_static_cohort(self) -> Cohort:
        return Cohort.objects.create(team=self.team, groups=[], is_static=True, name="test cohort")

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch("posthog.models.cohort.util.get_static_cohort_size", return_value=0)
    def test_removes_existing_cohort_member(self, mock_get_size, mock_remove_ch):
        person = Person.objects.create(team=self.team, distinct_ids=["d1"])

        cohort = self._create_static_cohort()
        CohortPeople.objects.create(cohort=cohort, person=person)

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.id,
                person_id=person.id,
                uuid=str(person.uuid),
                distinct_ids=["d1"],
            )

            result = cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is True
        assert not CohortPeople.objects.filter(cohort=cohort, person=person).exists()
        mock_remove_ch.assert_called_once()
        call_args = mock_remove_ch.call_args
        # personhog converter now returns uuid.UUID, matching the ORM type
        assert call_args[0][0] == person.uuid
        assert call_args[0][1] == cohort.pk
        assert call_args[1]["team_id"] == self.team.id

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch("posthog.models.cohort.util.get_static_cohort_size", return_value=0)
    def test_returns_true_for_person_not_in_cohort(self, mock_get_size, mock_remove_ch):
        """Person exists but is not a member of the cohort — should still return True
        and attempt ClickHouse removal (idempotent)."""
        person = Person.objects.create(team=self.team, distinct_ids=["d1"])

        cohort = self._create_static_cohort()

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.id,
                person_id=person.id,
                uuid=str(person.uuid),
                distinct_ids=["d1"],
            )

            result = cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is True
        # CH removal still attempted — idempotent
        mock_remove_ch.assert_called_once()

    def test_returns_false_for_nonexistent_person(self):
        cohort = self._create_static_cohort()

        with fake_personhog_client():
            # No person added to fake → get_person_by_uuid returns None
            result = cohort.remove_user_by_uuid("00000000-0000-0000-0000-000000000000", team_id=self.team.id)

        assert result is False

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch("posthog.models.cohort.util.get_static_cohort_size", return_value=0)
    def test_cross_team_isolation(self, mock_get_size, mock_remove_ch):
        """A person in team B should not be found when removing from team A's cohort."""
        other_team = Team.objects.create(organization=self.organization)
        person = Person.objects.create(team=other_team, distinct_ids=["d1"])

        cohort = self._create_static_cohort()

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=other_team.id,
                person_id=person.id,
                uuid=str(person.uuid),
                distinct_ids=["d1"],
            )

            result = cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is False
        mock_remove_ch.assert_not_called()

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch("posthog.models.cohort.util.get_static_cohort_size", return_value=5)
    def test_updates_cohort_count_after_removal(self, mock_get_size, mock_remove_ch):
        person = Person.objects.create(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()
        CohortPeople.objects.create(cohort=cohort, person=person)

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.id,
                person_id=person.id,
                uuid=str(person.uuid),
                distinct_ids=["d1"],
            )

            cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        cohort.refresh_from_db()
        assert cohort.count == 5  # Whatever get_static_cohort_size returns

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch(
        "posthog.models.cohort.util.get_static_cohort_size",
        side_effect=Exception("count failed"),
    )
    def test_count_error_does_not_prevent_removal(self, mock_get_size, mock_remove_ch):
        """If updating the count fails, the removal itself should still succeed."""
        person = Person.objects.create(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()
        CohortPeople.objects.create(cohort=cohort, person=person)

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.id,
                person_id=person.id,
                uuid=str(person.uuid),
                distinct_ids=["d1"],
            )

            result = cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is True
        assert not CohortPeople.objects.filter(cohort=cohort, person=person).exists()
        mock_remove_ch.assert_called_once()

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch("posthog.models.cohort.util.get_static_cohort_size", return_value=0)
    def test_personhog_resolves_person_for_removal(self, mock_get_size, mock_remove_ch):
        """Verify that the personhog fake is actually used to resolve the person
        (not the ORM), by checking the fake's call log."""
        person = Person.objects.create(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.id,
                person_id=person.id,
                uuid=str(person.uuid),
                distinct_ids=["d1"],
            )

            cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

            fake.assert_called("get_person_by_uuid")
