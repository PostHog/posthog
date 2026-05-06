"""Tests that cohort person-lookup methods produce identical results
via the ORM and personhog paths."""

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db.models import Q

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
        self._seed_cohort_membership(person_id=person.id, cohort_id=cohort.id, is_member=True)

        result = cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is True
        if self.personhog:
            assert self._fake_client is not None
            assert (cohort.id, person.id) not in self._fake_client._cohort_members
        else:
            assert not CohortPeople.objects.filter(cohort=cohort, person=person).exists()
        mock_remove_ch.assert_called_once()
        call_args = mock_remove_ch.call_args
        assert call_args[0][0] == person.uuid
        assert call_args[0][1] == cohort.pk
        assert call_args[1]["team_id"] == self.team.id
        self._assert_personhog_called("check_cohort_membership")

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
    @patch("posthog.models.cohort.util.get_static_cohort_size", return_value=0)
    def test_does_not_delete_when_cohort_belongs_to_other_team(self, mock_get_size, mock_remove_ch):
        """Calling remove_user_by_uuid with a team_id that does not own the
        cohort must not touch CohortPeople rows for that cohort."""
        other_team = Team.objects.create(organization=self.organization)
        person = self._seed_person(team=other_team, distinct_ids=["d1"])
        # Cohort lives on other_team; caller claims to be self.team.
        other_team_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")
        CohortPeople.objects.create(cohort=other_team_cohort, person=person)
        self._seed_cohort_membership(person_id=person.id, cohort_id=other_team_cohort.id, is_member=True)

        result = other_team_cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        # Person isn't resolvable under self.team → removal is a no-op (returns False)
        # and the CohortPeople row for the other team's cohort stays put.
        assert result is False
        assert CohortPeople.objects.filter(cohort=other_team_cohort, person=person).exists()
        mock_remove_ch.assert_not_called()

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch("posthog.models.cohort.util.get_static_cohort_size", return_value=5)
    def test_updates_cohort_count_after_removal(self, mock_get_size, mock_remove_ch):
        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()
        CohortPeople.objects.create(cohort=cohort, person=person)
        self._seed_cohort_membership(person_id=person.id, cohort_id=cohort.id, is_member=True)

        cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        cohort.refresh_from_db()
        assert cohort.count == 5

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch("posthog.models.cohort.util.get_static_cohort_size", side_effect=Exception("count failed"))
    def test_count_error_does_not_prevent_removal(self, mock_get_size, mock_remove_ch):
        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()
        CohortPeople.objects.create(cohort=cohort, person=person)
        self._seed_cohort_membership(person_id=person.id, cohort_id=cohort.id, is_member=True)

        result = cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is True
        if self.personhog:
            assert self._fake_client is not None
            assert (cohort.id, person.id) not in self._fake_client._cohort_members
        else:
            assert not CohortPeople.objects.filter(cohort=cohort, person=person).exists()
        mock_remove_ch.assert_called_once()

    @patch("posthog.models.cohort.util.remove_person_from_static_cohort")
    @patch("posthog.models.cohort.util.get_static_cohort_size", return_value=0)
    def test_personhog_resolves_person_for_removal(self, mock_get_size, mock_remove_ch):
        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()

        cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        self._assert_personhog_called("get_person_by_uuid")


@parameterized_class(("personhog",), [(False,), (True,)])
class TestCheckCohortMembership(PersonhogTestMixin, BaseTest):
    def test_returns_true_for_member(self):
        from posthog.models.cohort.util import check_cohort_membership, is_person_in_cohort

        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        CohortPeople.objects.create(cohort=cohort, person=person)
        self._seed_cohort_membership(person_id=person.id, cohort_id=cohort.id, is_member=True)

        assert is_person_in_cohort(team_id=self.team.id, person_id=person.id, cohort_id=cohort.id) is True
        assert check_cohort_membership(self.team.id, person.id, [cohort.id]) == {cohort.id: True}
        self._assert_personhog_called("check_cohort_membership")

    def test_returns_false_for_non_member(self):
        from posthog.models.cohort.util import is_person_in_cohort

        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")

        assert is_person_in_cohort(team_id=self.team.id, person_id=person.id, cohort_id=cohort.id) is False

    def test_returns_empty_dict_for_empty_cohort_ids(self):
        from posthog.models.cohort.util import check_cohort_membership

        person = self._seed_person(team=self.team, distinct_ids=["d1"])

        assert check_cohort_membership(self.team.id, person.id, []) == {}
        self._assert_personhog_not_called("check_cohort_membership")

    def test_mixed_membership(self):
        from posthog.models.cohort.util import check_cohort_membership

        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        c1 = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        c2 = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c2")
        c3 = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c3")
        CohortPeople.objects.create(cohort=c1, person=person)
        CohortPeople.objects.create(cohort=c3, person=person)
        self._seed_cohort_membership(person_id=person.id, cohort_id=c1.id, is_member=True)
        self._seed_cohort_membership(person_id=person.id, cohort_id=c3.id, is_member=True)

        result = check_cohort_membership(self.team.id, person.id, [c1.id, c2.id, c3.id])

        assert result == {c1.id: True, c2.id: False, c3.id: True}

    def test_isolates_cross_team_cohort(self):
        """Cohorts belonging to other teams must not leak into results, regardless
        of which path (personhog vs ORM) runs. Tenant scoping happens in the
        public wrapper before dispatch, so the RPC is never called for
        out-of-team cohort_ids."""
        from posthog.models.cohort.util import check_cohort_membership

        other_team = Team.objects.create(organization=self.organization)
        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        other_team_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")
        # Plant a real CohortPeople row (ORM-path leak canary) and a fake
        # membership (personhog-path leak canary). If scoping were missing on
        # either path the assertion would flip to True.
        CohortPeople.objects.create(cohort=other_team_cohort, person=person)
        self._seed_cohort_membership(person_id=person.id, cohort_id=other_team_cohort.id, is_member=True)

        result = check_cohort_membership(self.team.id, person.id, [other_team_cohort.id])

        assert result == {other_team_cohort.id: False}
        self._assert_personhog_not_called("check_cohort_membership")

    def test_isolates_cross_team_cohort_mixed_with_in_team(self):
        """When a mix of in-team and out-of-team cohort_ids is passed, only the
        in-team ones reach downstream; the caller still gets a dict keyed by
        every requested id with out-of-team ones reported as non-member."""
        from posthog.models.cohort.util import check_cohort_membership

        other_team = Team.objects.create(organization=self.organization)
        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        in_team_cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="in")
        other_team_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="out")
        CohortPeople.objects.create(cohort=in_team_cohort, person=person)
        CohortPeople.objects.create(cohort=other_team_cohort, person=person)
        self._seed_cohort_membership(person_id=person.id, cohort_id=in_team_cohort.id, is_member=True)
        self._seed_cohort_membership(person_id=person.id, cohort_id=other_team_cohort.id, is_member=True)

        result = check_cohort_membership(self.team.id, person.id, [in_team_cohort.id, other_team_cohort.id])

        assert result == {in_team_cohort.id: True, other_team_cohort.id: False}


class TestCheckCohortMembershipFallback(BaseTest):
    """Routing test: verifies ORM fallback when the personhog gate is disabled."""

    def test_falls_back_to_orm_when_personhog_disabled(self):
        from posthog.models.cohort.util import is_person_in_cohort

        person = Person.objects.create(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        CohortPeople.objects.create(cohort=cohort, person=person)

        with fake_personhog_client(gate_enabled=False) as fake:
            assert is_person_in_cohort(team_id=self.team.id, person_id=person.id, cohort_id=cohort.id) is True

        fake.assert_not_called("check_cohort_membership")


@parameterized_class(("personhog",), [(False,), (True,)])
class TestPropertyToQStaticCohortShortCircuit(PersonhogTestMixin, BaseTest):
    """property_to_Q short-circuits the Exists(CohortPeople) subquery when
    caller passes person_id + team_id for a static cohort."""

    def _make_cohort_property(self, cohort_id: int):
        from posthog.models.property import Property

        return Property(key="id", value=cohort_id, type="cohort")

    def test_returns_match_all_q_when_person_is_member(self):
        from posthog.queries.base import property_to_Q

        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        CohortPeople.objects.create(cohort=cohort, person=person)
        self._seed_cohort_membership(person_id=person.id, cohort_id=cohort.id, is_member=True)

        q = property_to_Q(
            self.team.project_id,
            self._make_cohort_property(cohort.id),
            person_id=person.id,
            team_id=self.team.id,
        )

        assert q == Q(pk__isnull=False)
        self._assert_personhog_called("check_cohort_membership")

    def test_returns_no_match_q_when_person_is_not_member(self):
        from posthog.queries.base import property_to_Q

        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")

        q = property_to_Q(
            self.team.project_id,
            self._make_cohort_property(cohort.id),
            person_id=person.id,
            team_id=self.team.id,
        )

        assert q == Q(pk__isnull=True)

    def test_falls_back_to_exists_without_person_id_or_team_id(self):
        from posthog.queries.base import property_to_Q

        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        CohortPeople.objects.create(cohort=cohort, person=person)

        q = property_to_Q(self.team.project_id, self._make_cohort_property(cohort.id))

        # Not a short-circuit Q — it's an Exists() wrapped in Q
        assert q != Q(pk__isnull=False)
        assert q != Q(pk__isnull=True)
        # The Exists subquery path never calls either RPC
        self._assert_personhog_not_called("check_cohort_membership")
        self._assert_personhog_not_called("list_cohort_member_ids")

    def test_isolates_cohort_by_team_id(self):
        """A cohort owned by a different team (even within the same project)
        must resolve to Q(pk__isnull=True), regardless of any CohortPeople
        rows or fake memberships set up for it."""
        from posthog.queries.base import property_to_Q

        other_team = self.organization.teams.create(name="other", project=self.team.project)
        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        other_team_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")
        # Plant a CohortPeople row and (in the personhog run) a fake membership
        # so that a missing team scope would show up as a false positive.
        CohortPeople.objects.create(cohort=other_team_cohort, person=person)
        self._seed_cohort_membership(person_id=person.id, cohort_id=other_team_cohort.id, is_member=True)

        q = property_to_Q(
            self.team.project_id,
            self._make_cohort_property(other_team_cohort.id),
            person_id=person.id,
            team_id=self.team.id,
        )

        assert q == Q(pk__isnull=True)


@parameterized_class(("personhog",), [(False,), (True,)])
class TestListCohortMemberIds(PersonhogTestMixin, BaseTest):
    def test_returns_member_ids(self):
        from posthog.models.cohort.util import list_cohort_member_ids

        p1 = self._seed_person(team=self.team, distinct_ids=["d1"])
        p2 = self._seed_person(team=self.team, distinct_ids=["d2"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        CohortPeople.objects.create(cohort=cohort, person=p1)
        CohortPeople.objects.create(cohort=cohort, person=p2)
        self._seed_cohort_membership(person_id=p1.id, cohort_id=cohort.id, is_member=True)
        self._seed_cohort_membership(person_id=p2.id, cohort_id=cohort.id, is_member=True)

        result = list_cohort_member_ids(team_id=self.team.id, cohort_id=cohort.id)

        assert sorted(result) == sorted([p1.id, p2.id])
        self._assert_personhog_called("list_cohort_member_ids")

    def test_returns_empty_for_empty_cohort(self):
        from posthog.models.cohort.util import list_cohort_member_ids

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")

        result = list_cohort_member_ids(team_id=self.team.id, cohort_id=cohort.id)

        assert result == []

    def test_excludes_non_members(self):
        from posthog.models.cohort.util import list_cohort_member_ids

        p1 = self._seed_person(team=self.team, distinct_ids=["d1"])
        p2 = self._seed_person(team=self.team, distinct_ids=["d2"])
        c1 = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        c2 = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c2")
        CohortPeople.objects.create(cohort=c1, person=p1)
        CohortPeople.objects.create(cohort=c2, person=p2)
        self._seed_cohort_membership(person_id=p1.id, cohort_id=c1.id, is_member=True)
        self._seed_cohort_membership(person_id=p2.id, cohort_id=c2.id, is_member=True)

        result = list_cohort_member_ids(team_id=self.team.id, cohort_id=c1.id)

        assert result == [p1.id]

    def test_isolates_cross_team_cohort(self):
        from posthog.models.cohort.util import list_cohort_member_ids

        other_team = Team.objects.create(organization=self.organization)
        person = self._seed_person(team=other_team, distinct_ids=["d1"])
        other_team_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")
        CohortPeople.objects.create(cohort=other_team_cohort, person=person)
        self._seed_cohort_membership(person_id=person.id, cohort_id=other_team_cohort.id, is_member=True)

        result = list_cohort_member_ids(team_id=self.team.id, cohort_id=other_team_cohort.id)

        assert result == []
        self._assert_personhog_not_called("list_cohort_member_ids")


class TestListCohortMemberIdsFallback(BaseTest):
    def test_falls_back_to_orm_when_personhog_disabled(self):
        from posthog.models.cohort.util import list_cohort_member_ids

        person = Person.objects.create(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        CohortPeople.objects.create(cohort=cohort, person=person)

        with fake_personhog_client(gate_enabled=False) as fake:
            result = list_cohort_member_ids(team_id=self.team.id, cohort_id=cohort.id)

        assert result == [person.id]
        fake.assert_not_called("list_cohort_member_ids")


@parameterized_class(("personhog",), [(False,), (True,)])
class TestPropertyToQStaticCohortMemberList(PersonhogTestMixin, BaseTest):
    """property_to_Q uses list_cohort_member_ids to produce Q(id__in=…) when
    team_id is provided but person_id is not (queryset-wide filtering)."""

    def _make_cohort_property(self, cohort_id: int):
        from posthog.models.property import Property

        return Property(key="id", value=cohort_id, type="cohort")

    def test_returns_id_in_q_with_team_id_and_no_person_id(self):
        from posthog.queries.base import property_to_Q

        p1 = self._seed_person(team=self.team, distinct_ids=["d1"])
        p2 = self._seed_person(team=self.team, distinct_ids=["d2"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        CohortPeople.objects.create(cohort=cohort, person=p1)
        CohortPeople.objects.create(cohort=cohort, person=p2)
        self._seed_cohort_membership(person_id=p1.id, cohort_id=cohort.id, is_member=True)
        self._seed_cohort_membership(person_id=p2.id, cohort_id=cohort.id, is_member=True)

        q = property_to_Q(
            self.team.project_id,
            self._make_cohort_property(cohort.id),
            team_id=self.team.id,
        )

        matched = Person.objects.filter(team_id=self.team.id).filter(q)
        assert sorted(matched.values_list("id", flat=True)) == sorted([p1.id, p2.id])
        self._assert_personhog_called("list_cohort_member_ids")

    def test_returns_no_match_for_empty_cohort(self):
        from posthog.queries.base import property_to_Q

        self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")

        q = property_to_Q(
            self.team.project_id,
            self._make_cohort_property(cohort.id),
            team_id=self.team.id,
        )

        assert q == Q(pk__isnull=True)

    def test_filters_correctly_with_queryset(self):
        from posthog.queries.base import property_to_Q

        member = self._seed_person(team=self.team, distinct_ids=["member"])
        non_member = self._seed_person(team=self.team, distinct_ids=["outsider"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        CohortPeople.objects.create(cohort=cohort, person=member)
        self._seed_cohort_membership(person_id=member.id, cohort_id=cohort.id, is_member=True)

        q = property_to_Q(
            self.team.project_id,
            self._make_cohort_property(cohort.id),
            team_id=self.team.id,
        )

        matched = set(Person.objects.filter(team_id=self.team.id).filter(q).values_list("id", flat=True))
        assert member.id in matched
        assert non_member.id not in matched


@parameterized_class(("personhog",), [(False,), (True,)])
class TestInsertCohortMembers(PersonhogTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _create_static_cohort(self) -> Cohort:
        return Cohort.objects.create(team=self.team, groups=[], is_static=True, name="test cohort")

    def test_inserts_members(self):
        from posthog.models.cohort.util import insert_cohort_members

        p1 = self._seed_person(team=self.team, distinct_ids=["d1"])
        p2 = self._seed_person(team=self.team, distinct_ids=["d2"])
        cohort = self._create_static_cohort()

        inserted = insert_cohort_members(self.team.id, cohort.id, [p1.id, p2.id], version=1)

        assert inserted > 0
        if self.personhog:
            assert self._fake_client is not None
            assert (cohort.id, p1.id) in self._fake_client._cohort_members
            assert (cohort.id, p2.id) in self._fake_client._cohort_members
        else:
            assert CohortPeople.objects.filter(cohort=cohort).count() == 2
        self._assert_personhog_called("insert_cohort_members")

    def test_deduplicates_existing_members(self):
        from posthog.models.cohort.util import insert_cohort_members

        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()
        CohortPeople.objects.create(cohort=cohort, person=person)
        self._seed_cohort_membership(person_id=person.id, cohort_id=cohort.id, is_member=True)

        inserted = insert_cohort_members(self.team.id, cohort.id, [person.id], version=1)

        if self.personhog:
            assert inserted == 0
        else:
            assert CohortPeople.objects.filter(cohort=cohort).count() == 1

    def test_returns_zero_for_empty_list(self):
        from posthog.models.cohort.util import insert_cohort_members

        cohort = self._create_static_cohort()

        assert insert_cohort_members(self.team.id, cohort.id, [], version=1) == 0
        self._assert_personhog_not_called("insert_cohort_members")

    def test_rejects_cross_team_cohort(self):
        from posthog.models.cohort.util import insert_cohort_members

        other_team = Team.objects.create(organization=self.organization)
        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        other_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")

        inserted = insert_cohort_members(self.team.id, other_cohort.id, [person.id], version=1)

        assert inserted == 0
        assert not CohortPeople.objects.filter(cohort=other_cohort).exists()
        self._assert_personhog_not_called("insert_cohort_members")

    def test_skip_ownership_check_bypasses_team_validation(self):
        from posthog.models.cohort.util import insert_cohort_members

        other_team = Team.objects.create(organization=self.organization)
        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")
        self._seed_cohort_membership(person_id=person.id, cohort_id=cohort.id, is_member=False)

        inserted = insert_cohort_members(self.team.id, cohort.id, [person.id], version=1, _skip_ownership_check=True)

        assert inserted > 0
        self._assert_personhog_called("insert_cohort_members")


class TestInsertCohortMembersFallback(BaseTest):
    def test_falls_back_to_orm_when_personhog_disabled(self):
        from posthog.models.cohort.util import insert_cohort_members

        person = Person.objects.create(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")

        with fake_personhog_client(gate_enabled=False) as fake:
            insert_cohort_members(self.team.id, cohort.id, [person.id], version=1)

        assert CohortPeople.objects.filter(cohort=cohort, person=person).exists()
        fake.assert_not_called("insert_cohort_members")


@parameterized_class(("personhog",), [(False,), (True,)])
class TestDeleteCohortMember(PersonhogTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _create_static_cohort(self) -> Cohort:
        return Cohort.objects.create(team=self.team, groups=[], is_static=True, name="test cohort")

    def test_deletes_existing_member(self):
        from posthog.models.cohort.util import delete_cohort_member

        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()
        CohortPeople.objects.create(cohort=cohort, person=person)
        self._seed_cohort_membership(person_id=person.id, cohort_id=cohort.id, is_member=True)

        result = delete_cohort_member(self.team.id, cohort.id, person.id)

        assert result is True
        if not self.personhog:
            assert not CohortPeople.objects.filter(cohort=cohort, person=person).exists()
        self._assert_personhog_called("delete_cohort_member")

    def test_returns_false_for_non_member(self):
        from posthog.models.cohort.util import delete_cohort_member

        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()

        result = delete_cohort_member(self.team.id, cohort.id, person.id)

        assert result is False

    def test_rejects_cross_team_cohort(self):
        from posthog.models.cohort.util import delete_cohort_member

        other_team = Team.objects.create(organization=self.organization)
        person = self._seed_person(team=other_team, distinct_ids=["d1"])
        other_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")
        CohortPeople.objects.create(cohort=other_cohort, person=person)
        self._seed_cohort_membership(person_id=person.id, cohort_id=other_cohort.id, is_member=True)

        result = delete_cohort_member(self.team.id, other_cohort.id, person.id)

        assert result is False
        assert CohortPeople.objects.filter(cohort=other_cohort, person=person).exists()
        self._assert_personhog_not_called("delete_cohort_member")


class TestDeleteCohortMemberFallback(BaseTest):
    def test_falls_back_to_orm_when_personhog_disabled(self):
        from posthog.models.cohort.util import delete_cohort_member

        person = Person.objects.create(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        CohortPeople.objects.create(cohort=cohort, person=person)

        with fake_personhog_client(gate_enabled=False) as fake:
            result = delete_cohort_member(self.team.id, cohort.id, person.id)

        assert result is True
        assert not CohortPeople.objects.filter(cohort=cohort, person=person).exists()
        fake.assert_not_called("delete_cohort_member")


@parameterized_class(("personhog",), [(False,), (True,)])
class TestDeleteCohortMembersBulk(PersonhogTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_deletes_all_members_for_cohorts(self):
        from posthog.models.cohort.util import delete_cohort_members_bulk

        p1 = self._seed_person(team=self.team, distinct_ids=["d1"])
        p2 = self._seed_person(team=self.team, distinct_ids=["d2"])
        c1 = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        c2 = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c2")
        CohortPeople.objects.create(cohort=c1, person=p1)
        CohortPeople.objects.create(cohort=c2, person=p2)
        self._seed_cohort_membership(person_id=p1.id, cohort_id=c1.id, is_member=True)
        self._seed_cohort_membership(person_id=p2.id, cohort_id=c2.id, is_member=True)

        deleted = delete_cohort_members_bulk(self.team.id, [c1.id, c2.id])

        assert deleted >= 2
        if not self.personhog:
            assert CohortPeople.objects.filter(cohort_id__in=[c1.id, c2.id]).count() == 0
        self._assert_personhog_called("delete_cohort_members_bulk")

    def test_returns_zero_for_empty_list(self):
        from posthog.models.cohort.util import delete_cohort_members_bulk

        assert delete_cohort_members_bulk(self.team.id, []) == 0
        self._assert_personhog_not_called("delete_cohort_members_bulk")


class TestDeleteCohortMembersBulkFallback(BaseTest):
    def test_falls_back_to_orm_when_personhog_disabled(self):
        from posthog.models.cohort.util import delete_cohort_members_bulk

        person = Person.objects.create(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        CohortPeople.objects.create(cohort=cohort, person=person)

        with fake_personhog_client(gate_enabled=False) as fake:
            deleted = delete_cohort_members_bulk(self.team.id, [cohort.id])

        assert deleted == 1
        assert not CohortPeople.objects.filter(cohort=cohort).exists()
        fake.assert_not_called("delete_cohort_members_bulk")


class TestDeleteCohortMembersBulkMaxIterations(BaseTest):
    def test_stops_after_max_iterations(self):
        from unittest.mock import MagicMock

        from posthog.models.cohort import util as cohort_util
        from posthog.personhog_client.proto import DeleteCohortMembersBulkResponse

        mock_client = MagicMock()
        mock_client.delete_cohort_members_bulk.return_value = DeleteCohortMembersBulkResponse(deleted_count=100)

        max_iters = 5
        with (
            patch.object(cohort_util, "_DELETE_BULK_MAX_ITERATIONS", max_iters),
            patch("posthog.personhog_client.client.get_personhog_client", return_value=mock_client),
        ):
            total = cohort_util._delete_cohort_members_bulk_via_personhog([1], batch_size=100)

        assert mock_client.delete_cohort_members_bulk.call_count == max_iters
        assert total == 100 * max_iters


@parameterized_class(("personhog",), [(False,), (True,)])
class TestCountCohortMembers(PersonhogTestMixin, BaseTest):
    def test_returns_count(self):
        from posthog.models.cohort.util import count_cohort_members

        p1 = self._seed_person(team=self.team, distinct_ids=["d1"])
        p2 = self._seed_person(team=self.team, distinct_ids=["d2"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        CohortPeople.objects.create(cohort=cohort, person=p1)
        CohortPeople.objects.create(cohort=cohort, person=p2)
        self._seed_cohort_membership(person_id=p1.id, cohort_id=cohort.id, is_member=True)
        self._seed_cohort_membership(person_id=p2.id, cohort_id=cohort.id, is_member=True)

        assert count_cohort_members(self.team.id, cohort.id) == 2
        self._assert_personhog_called("count_cohort_members")

    def test_returns_zero_for_empty_cohort(self):
        from posthog.models.cohort.util import count_cohort_members

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")

        assert count_cohort_members(self.team.id, cohort.id) == 0

    def test_isolates_cross_team_cohort(self):
        from posthog.models.cohort.util import count_cohort_members

        other_team = Team.objects.create(organization=self.organization)
        person = self._seed_person(team=other_team, distinct_ids=["d1"])
        other_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")
        CohortPeople.objects.create(cohort=other_cohort, person=person)
        self._seed_cohort_membership(person_id=person.id, cohort_id=other_cohort.id, is_member=True)

        assert count_cohort_members(self.team.id, other_cohort.id) == 0
        self._assert_personhog_not_called("count_cohort_members")


class TestCountCohortMembersFallback(BaseTest):
    def test_falls_back_to_orm_when_personhog_disabled(self):
        from posthog.models.cohort.util import count_cohort_members

        person = Person.objects.create(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        CohortPeople.objects.create(cohort=cohort, person=person)

        with fake_personhog_client(gate_enabled=False) as fake:
            assert count_cohort_members(self.team.id, cohort.id) == 1

        fake.assert_not_called("count_cohort_members")


@parameterized_class(("personhog",), [(False,), (True,)])
class TestInsertUsersListWithBatchingPersonhog(PersonhogTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _create_static_cohort(self) -> Cohort:
        return Cohort.objects.create(team=self.team, groups=[], is_static=True, name="test cohort")

    @patch("posthog.models.cohort.util.insert_static_cohort")
    def test_insert_users_by_uuid(self, mock_insert_ch):
        p1 = self._seed_person(team=self.team, distinct_ids=["d1"])
        p2 = self._seed_person(team=self.team, distinct_ids=["d2"])
        cohort = self._create_static_cohort()

        cohort.insert_users_list_by_uuid([str(p1.uuid), str(p2.uuid)], team_id=self.team.id)

        if self.personhog:
            self._assert_personhog_called("insert_cohort_members")
        else:
            assert CohortPeople.objects.filter(cohort=cohort).count() == 2

    @patch("posthog.models.cohort.util.insert_static_cohort")
    def test_insert_users_by_distinct_id(self, mock_insert_ch):
        self._seed_person(team=self.team, distinct_ids=["d1"])
        self._seed_person(team=self.team, distinct_ids=["d2"])
        cohort = self._create_static_cohort()

        cohort.insert_users_by_list(["d1", "d2"], team_id=self.team.id)

        if self.personhog:
            self._assert_personhog_called("insert_cohort_members")
        else:
            assert CohortPeople.objects.filter(cohort=cohort).count() == 2

    @patch("posthog.models.cohort.util.insert_static_cohort")
    def test_insert_idempotent(self, mock_insert_ch):
        person = self._seed_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()

        cohort.insert_users_list_by_uuid([str(person.uuid)], team_id=self.team.id)
        cohort.insert_users_list_by_uuid([str(person.uuid)], team_id=self.team.id)

        if not self.personhog:
            assert CohortPeople.objects.filter(cohort=cohort).count() == 1
