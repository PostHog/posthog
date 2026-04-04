"""Tests that cohort person-lookup methods produce identical results
via the ORM and personhog paths."""

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized_class

from posthog.models import Cohort, Person, Team
from posthog.models.cohort.cohort import CohortPeople
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.personhog_client.test_helpers import PersonhogTestMixin


@parameterized_class(("personhog",), [(False,), (True,)])
class TestGetUuidsForDistinctIdsBatch(PersonhogTestMixin, BaseTest):
    def _create_static_cohort(self) -> Cohort:
        return Cohort.objects.create(team=self.team, groups=[], is_static=True, name="test cohort")

    def test_returns_uuids_for_matching_distinct_ids(self):
        p1 = self._seed_person(team=self.team, distinct_ids=["d1", "d2"])
        p2 = self._seed_person(team=self.team, distinct_ids=["d3"])

        cohort = self._create_static_cohort()
        result = cohort._get_uuids_for_distinct_ids_batch(["d1", "d3"], team_id=self.team.pk)

        assert set(result) == {str(p1.uuid), str(p2.uuid)}
        self._assert_personhog_called("get_persons_by_distinct_ids_in_team")

    def test_returns_empty_list_for_empty_input(self):
        cohort = self._create_static_cohort()
        result = cohort._get_uuids_for_distinct_ids_batch([], team_id=self.team.pk)

        assert result == []
        self._assert_personhog_not_called("get_persons_by_distinct_ids_in_team")

    def test_returns_empty_list_when_no_persons_match(self):
        cohort = self._create_static_cohort()
        result = cohort._get_uuids_for_distinct_ids_batch(["nonexistent"], team_id=self.team.pk)

        assert result == []

    def test_cross_team_isolation(self):
        other_team = self.organization.teams.create(name="Other Team")
        self._seed_person(team=other_team, distinct_ids=["d1"])

        cohort = self._create_static_cohort()
        result = cohort._get_uuids_for_distinct_ids_batch(["d1"], team_id=self.team.pk)

        assert result == []

    def test_deduplicates_persons_with_multiple_distinct_ids(self):
        p = self._seed_person(team=self.team, distinct_ids=["d1", "d2", "d3"])

        cohort = self._create_static_cohort()
        result = cohort._get_uuids_for_distinct_ids_batch(["d1", "d2", "d3"], team_id=self.team.pk)

        assert result == [str(p.uuid)]

    def test_handles_mix_of_found_and_missing_distinct_ids(self):
        p = self._seed_person(team=self.team, distinct_ids=["exists"])

        cohort = self._create_static_cohort()
        result = cohort._get_uuids_for_distinct_ids_batch(["exists", "missing1", "missing2"], team_id=self.team.pk)

        assert result == [str(p.uuid)]

    def test_multiple_persons_each_with_single_distinct_id(self):
        persons = [self._seed_person(team=self.team, distinct_ids=[f"d{i}"]) for i in range(5)]

        cohort = self._create_static_cohort()
        result = cohort._get_uuids_for_distinct_ids_batch([f"d{i}" for i in range(5)], team_id=self.team.pk)

        assert set(result) == {str(p.uuid) for p in persons}


class TestGetUuidsForDistinctIdsBatchFallback(BaseTest):
    """Routing test: verifies ORM fallback when the personhog gate is disabled."""

    def test_falls_back_to_orm_when_personhog_disabled(self):
        p = Person.objects.create(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="test cohort")

        with fake_personhog_client(gate_enabled=False) as fake:
            result = cohort._get_uuids_for_distinct_ids_batch(["d1"], team_id=self.team.pk)

        assert result == [str(p.uuid)]
        fake.assert_not_called("get_persons_by_distinct_ids_in_team")


@parameterized_class(("personhog",), [(False,), (True,)])
class TestRemoveUserByUuid(PersonhogTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _create_static_cohort(self) -> Cohort:
        return Cohort.objects.create(team=self.team, groups=[], is_static=True, name="test cohort")

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch("posthog.models.cohort.util.get_static_cohort_size", return_value=0)
    def test_removes_existing_cohort_member(self, mock_get_size, mock_remove_ch):
        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()
        CohortPeople.objects.create(cohort=cohort, person=person)

        result = cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is True
        assert not CohortPeople.objects.filter(cohort=cohort, person=person).exists()
        mock_remove_ch.assert_called_once()
        call_args = mock_remove_ch.call_args
        assert call_args[0][0] == person.uuid
        assert call_args[0][1] == cohort.pk
        assert call_args[1]["team_id"] == self.team.id

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch("posthog.models.cohort.util.get_static_cohort_size", return_value=0)
    def test_returns_true_for_person_not_in_cohort(self, mock_get_size, mock_remove_ch):
        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()

        result = cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is True
        mock_remove_ch.assert_called_once()

    def test_returns_false_for_nonexistent_person(self):
        cohort = self._create_static_cohort()

        result = cohort.remove_user_by_uuid("00000000-0000-0000-0000-000000000000", team_id=self.team.id)

        assert result is False

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch("posthog.models.cohort.util.get_static_cohort_size", return_value=0)
    def test_cross_team_isolation(self, mock_get_size, mock_remove_ch):
        other_team = Team.objects.create(organization=self.organization)
        person = self._seed_person(team=other_team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()

        result = cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is False
        mock_remove_ch.assert_not_called()

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch("posthog.models.cohort.util.get_static_cohort_size", return_value=5)
    def test_updates_cohort_count_after_removal(self, mock_get_size, mock_remove_ch):
        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()
        CohortPeople.objects.create(cohort=cohort, person=person)

        cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        cohort.refresh_from_db()
        assert cohort.count == 5

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch("posthog.models.cohort.util.get_static_cohort_size", side_effect=Exception("count failed"))
    def test_count_error_does_not_prevent_removal(self, mock_get_size, mock_remove_ch):
        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()
        CohortPeople.objects.create(cohort=cohort, person=person)

        result = cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is True
        assert not CohortPeople.objects.filter(cohort=cohort, person=person).exists()
        mock_remove_ch.assert_called_once()

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch("posthog.models.cohort.util.get_static_cohort_size", return_value=0)
    def test_personhog_resolves_person_for_removal(self, mock_get_size, mock_remove_ch):
        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()

        cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        self._assert_personhog_called("get_person_by_uuid")
