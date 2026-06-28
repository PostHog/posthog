"""Tests for cohort membership operations (insert, delete, count, list, check)."""

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import Team
from posthog.personhog_client.fake_client import get_active_fake
from posthog.test.persons import add_cohort_members, create_person

from products.cohorts.backend.models.cohort import Cohort


class TestRemoveUserByUuid(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _create_static_cohort(self) -> Cohort:
        return Cohort.objects.create(team=self.team, groups=[], is_static=True, name="test cohort")

    @patch("products.cohorts.backend.models.util.remove_person_from_static_cohort")
    @patch("products.cohorts.backend.models.util.get_static_cohort_size", return_value=0)
    def test_removes_existing_cohort_member(self, mock_get_size, mock_remove_ch):
        person = create_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()
        add_cohort_members(cohort, [person])

        result = cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is True
        assert (cohort.id, person.id) not in get_active_fake()._cohort_members
        mock_remove_ch.assert_called_once()
        call_args = mock_remove_ch.call_args
        assert call_args[0][0] == person.uuid
        assert call_args[0][1] == cohort.pk
        assert call_args[1]["team_id"] == self.team.id
        get_active_fake().assert_called("check_cohort_membership")

    @patch("products.cohorts.backend.models.util.remove_person_from_static_cohort")
    @patch("products.cohorts.backend.models.util.get_static_cohort_size", return_value=0)
    def test_returns_true_for_person_not_in_cohort(self, mock_get_size, mock_remove_ch):
        person = create_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()

        result = cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is True
        mock_remove_ch.assert_called_once()

    def test_returns_false_for_nonexistent_person(self):
        cohort = self._create_static_cohort()

        result = cohort.remove_user_by_uuid("00000000-0000-0000-0000-000000000000", team_id=self.team.id)

        assert result is False

    @patch("products.cohorts.backend.models.util.remove_person_from_static_cohort")
    @patch("products.cohorts.backend.models.util.get_static_cohort_size", return_value=0)
    def test_cross_team_isolation(self, mock_get_size, mock_remove_ch):
        other_team = Team.objects.create(organization=self.organization)
        person = create_person(team=other_team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()

        result = cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is False
        mock_remove_ch.assert_not_called()

    @patch("products.cohorts.backend.models.util.remove_person_from_static_cohort")
    @patch("products.cohorts.backend.models.util.get_static_cohort_size", return_value=0)
    def test_does_not_delete_when_cohort_belongs_to_other_team(self, mock_get_size, mock_remove_ch):
        """Calling remove_user_by_uuid with a team_id that does not own the
        cohort must not touch CohortPeople rows for that cohort."""
        other_team = Team.objects.create(organization=self.organization)
        person = create_person(team=other_team, distinct_ids=["d1"])
        other_team_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")
        add_cohort_members(other_team_cohort, [person])

        result = other_team_cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is False
        assert (other_team_cohort.id, person.id) in get_active_fake()._cohort_members
        mock_remove_ch.assert_not_called()

    @patch("products.cohorts.backend.models.util.remove_person_from_static_cohort")
    @patch("products.cohorts.backend.models.util.get_static_cohort_size", return_value=5)
    def test_updates_cohort_count_after_removal(self, mock_get_size, mock_remove_ch):
        person = create_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()
        add_cohort_members(cohort, [person])

        cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        cohort.refresh_from_db()
        assert cohort.count == 5

    @patch("products.cohorts.backend.models.util.remove_person_from_static_cohort")
    @patch("products.cohorts.backend.models.util.get_static_cohort_size", side_effect=Exception("count failed"))
    def test_count_error_does_not_prevent_removal(self, mock_get_size, mock_remove_ch):
        person = create_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()
        add_cohort_members(cohort, [person])

        result = cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        assert result is True
        assert (cohort.id, person.id) not in get_active_fake()._cohort_members
        mock_remove_ch.assert_called_once()

    @patch("products.cohorts.backend.models.util.remove_person_from_static_cohort")
    @patch("products.cohorts.backend.models.util.get_static_cohort_size", return_value=0)
    def test_personhog_resolves_person_for_removal(self, mock_get_size, mock_remove_ch):
        person = create_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()

        cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.id)

        get_active_fake().assert_called("get_person_by_uuid")


class TestCheckCohortMembership(BaseTest):
    def test_returns_true_for_member(self):
        from products.cohorts.backend.models.util import check_cohort_membership, is_person_in_cohort

        person = create_person(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        add_cohort_members(cohort, [person])

        assert is_person_in_cohort(team_id=self.team.id, person_id=person.id, cohort_id=cohort.id) is True
        assert check_cohort_membership(self.team.id, person.id, [cohort.id]) == {cohort.id: True}
        get_active_fake().assert_called("check_cohort_membership")

    def test_returns_false_for_non_member(self):
        from products.cohorts.backend.models.util import is_person_in_cohort

        person = create_person(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")

        assert is_person_in_cohort(team_id=self.team.id, person_id=person.id, cohort_id=cohort.id) is False

    def test_returns_empty_dict_for_empty_cohort_ids(self):
        from products.cohorts.backend.models.util import check_cohort_membership

        person = create_person(team=self.team, distinct_ids=["d1"])

        assert check_cohort_membership(self.team.id, person.id, []) == {}
        get_active_fake().assert_not_called("check_cohort_membership")

    def test_mixed_membership(self):
        from products.cohorts.backend.models.util import check_cohort_membership

        person = create_person(team=self.team, distinct_ids=["d1"])
        c1 = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        c2 = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c2")
        c3 = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c3")
        add_cohort_members(c1, [person])
        add_cohort_members(c3, [person])

        result = check_cohort_membership(self.team.id, person.id, [c1.id, c2.id, c3.id])

        assert result == {c1.id: True, c2.id: False, c3.id: True}

    def test_isolates_cross_team_cohort(self):
        """Cohorts belonging to other teams must not leak into results, regardless
        of which path (personhog vs ORM) runs. Tenant scoping happens in the
        public wrapper before dispatch, so the RPC is never called for
        out-of-team cohort_ids."""
        from products.cohorts.backend.models.util import check_cohort_membership

        other_team = Team.objects.create(organization=self.organization)
        person = create_person(team=self.team, distinct_ids=["d1"])
        other_team_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")
        add_cohort_members(other_team_cohort, [person])

        result = check_cohort_membership(self.team.id, person.id, [other_team_cohort.id])

        assert result == {other_team_cohort.id: False}
        get_active_fake().assert_not_called("check_cohort_membership")

    def test_isolates_cross_team_cohort_mixed_with_in_team(self):
        """When a mix of in-team and out-of-team cohort_ids is passed, only the
        in-team ones reach downstream; the caller still gets a dict keyed by
        every requested id with out-of-team ones reported as non-member."""
        from products.cohorts.backend.models.util import check_cohort_membership

        other_team = Team.objects.create(organization=self.organization)
        person = create_person(team=self.team, distinct_ids=["d1"])
        in_team_cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="in")
        other_team_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="out")
        add_cohort_members(in_team_cohort, [person])
        add_cohort_members(other_team_cohort, [person])

        result = check_cohort_membership(self.team.id, person.id, [in_team_cohort.id, other_team_cohort.id])

        assert result == {in_team_cohort.id: True, other_team_cohort.id: False}


class TestListCohortMemberIds(BaseTest):
    def test_returns_member_ids(self):
        from products.cohorts.backend.models.util import list_cohort_member_ids

        p1 = create_person(team=self.team, distinct_ids=["d1"])
        p2 = create_person(team=self.team, distinct_ids=["d2"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        add_cohort_members(cohort, [p1, p2])

        result = list_cohort_member_ids(team_id=self.team.id, cohort_id=cohort.id)

        assert sorted(result) == sorted([p1.id, p2.id])
        get_active_fake().assert_called("list_cohort_member_ids")

    def test_returns_empty_for_empty_cohort(self):
        from products.cohorts.backend.models.util import list_cohort_member_ids

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")

        result = list_cohort_member_ids(team_id=self.team.id, cohort_id=cohort.id)

        assert result == []

    def test_excludes_non_members(self):
        from products.cohorts.backend.models.util import list_cohort_member_ids

        p1 = create_person(team=self.team, distinct_ids=["d1"])
        p2 = create_person(team=self.team, distinct_ids=["d2"])
        c1 = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        c2 = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c2")
        add_cohort_members(c1, [p1])
        add_cohort_members(c2, [p2])

        result = list_cohort_member_ids(team_id=self.team.id, cohort_id=c1.id)

        assert result == [p1.id]

    def test_isolates_cross_team_cohort(self):
        from products.cohorts.backend.models.util import list_cohort_member_ids

        other_team = Team.objects.create(organization=self.organization)
        person = create_person(team=other_team, distinct_ids=["d1"])
        other_team_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")
        add_cohort_members(other_team_cohort, [person])

        result = list_cohort_member_ids(team_id=self.team.id, cohort_id=other_team_cohort.id)

        assert result == []
        get_active_fake().assert_not_called("list_cohort_member_ids")


class TestInsertCohortMembers(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _create_static_cohort(self) -> Cohort:
        return Cohort.objects.create(team=self.team, groups=[], is_static=True, name="test cohort")

    def test_inserts_members(self):
        from products.cohorts.backend.models.util import insert_cohort_members

        p1 = create_person(team=self.team, distinct_ids=["d1"])
        p2 = create_person(team=self.team, distinct_ids=["d2"])
        cohort = self._create_static_cohort()

        inserted = insert_cohort_members(self.team.id, cohort.id, [p1.id, p2.id], version=1)

        assert inserted > 0
        assert (cohort.id, p1.id) in get_active_fake()._cohort_members
        assert (cohort.id, p2.id) in get_active_fake()._cohort_members
        get_active_fake().assert_called("insert_cohort_members")

    def test_deduplicates_existing_members(self):
        from products.cohorts.backend.models.util import insert_cohort_members

        person = create_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()
        add_cohort_members(cohort, [person])

        inserted = insert_cohort_members(self.team.id, cohort.id, [person.id], version=1)

        assert inserted == 0

    def test_returns_zero_for_empty_list(self):
        from products.cohorts.backend.models.util import insert_cohort_members

        cohort = self._create_static_cohort()

        assert insert_cohort_members(self.team.id, cohort.id, [], version=1) == 0
        get_active_fake().assert_not_called("insert_cohort_members")

    def test_rejects_cross_team_cohort(self):
        from products.cohorts.backend.models.util import insert_cohort_members

        other_team = Team.objects.create(organization=self.organization)
        person = create_person(team=self.team, distinct_ids=["d1"])
        other_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")

        inserted = insert_cohort_members(self.team.id, other_cohort.id, [person.id], version=1)

        assert inserted == 0
        assert (other_cohort.id, person.id) not in get_active_fake()._cohort_members
        get_active_fake().assert_not_called("insert_cohort_members")

    def test_skip_ownership_check_bypasses_team_validation(self):
        from products.cohorts.backend.models.util import insert_cohort_members

        other_team = Team.objects.create(organization=self.organization)
        person = create_person(team=self.team, distinct_ids=["d1"])
        cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")
        get_active_fake().add_cohort_membership(person_id=person.id, cohort_id=cohort.id, is_member=False)

        inserted = insert_cohort_members(self.team.id, cohort.id, [person.id], version=1, _skip_ownership_check=True)

        assert inserted > 0
        get_active_fake().assert_called("insert_cohort_members")


class TestDeleteCohortMember(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _create_static_cohort(self) -> Cohort:
        return Cohort.objects.create(team=self.team, groups=[], is_static=True, name="test cohort")

    def test_deletes_existing_member(self):
        from products.cohorts.backend.models.util import delete_cohort_member

        person = create_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()
        add_cohort_members(cohort, [person])

        result = delete_cohort_member(self.team.id, cohort.id, person.id)

        assert result is True
        get_active_fake().assert_called("delete_cohort_member")

    def test_returns_false_for_non_member(self):
        from products.cohorts.backend.models.util import delete_cohort_member

        person = create_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()

        result = delete_cohort_member(self.team.id, cohort.id, person.id)

        assert result is False

    def test_rejects_cross_team_cohort(self):
        from products.cohorts.backend.models.util import delete_cohort_member

        other_team = Team.objects.create(organization=self.organization)
        person = create_person(team=other_team, distinct_ids=["d1"])
        other_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")
        add_cohort_members(other_cohort, [person])

        result = delete_cohort_member(self.team.id, other_cohort.id, person.id)

        assert result is False
        assert (other_cohort.id, person.id) in get_active_fake()._cohort_members
        get_active_fake().assert_not_called("delete_cohort_member")


class TestDeleteCohortMembersBulk(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_deletes_all_members_for_cohorts(self):
        from products.cohorts.backend.models.util import delete_cohort_members_bulk

        p1 = create_person(team=self.team, distinct_ids=["d1"])
        p2 = create_person(team=self.team, distinct_ids=["d2"])
        c1 = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        c2 = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c2")
        add_cohort_members(c1, [p1])
        add_cohort_members(c2, [p2])

        deleted = delete_cohort_members_bulk(self.team.id, [c1.id, c2.id])

        assert deleted >= 2
        get_active_fake().assert_called("delete_cohort_members_bulk")

    def test_returns_zero_for_empty_list(self):
        from products.cohorts.backend.models.util import delete_cohort_members_bulk

        assert delete_cohort_members_bulk(self.team.id, []) == 0
        get_active_fake().assert_not_called("delete_cohort_members_bulk")


class TestDeleteCohortMembersBulkMaxIterations(BaseTest):
    def test_stops_after_max_iterations(self):
        from unittest.mock import MagicMock

        from posthog.personhog_client.proto import DeleteCohortMembersBulkResponse

        from products.cohorts.backend.models import util as cohort_util

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


class TestCountCohortMembers(BaseTest):
    def test_returns_count(self):
        from products.cohorts.backend.models.util import count_cohort_members

        p1 = create_person(team=self.team, distinct_ids=["d1"])
        p2 = create_person(team=self.team, distinct_ids=["d2"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")
        add_cohort_members(cohort, [p1, p2])

        assert count_cohort_members(self.team.id, cohort.id) == 2
        get_active_fake().assert_called("count_cohort_members")

    def test_returns_zero_for_empty_cohort(self):
        from products.cohorts.backend.models.util import count_cohort_members

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, name="c1")

        assert count_cohort_members(self.team.id, cohort.id) == 0

    def test_isolates_cross_team_cohort(self):
        from products.cohorts.backend.models.util import count_cohort_members

        other_team = Team.objects.create(organization=self.organization)
        person = create_person(team=other_team, distinct_ids=["d1"])
        other_cohort = Cohort.objects.create(team=other_team, groups=[], is_static=True, name="other")
        add_cohort_members(other_cohort, [person])

        assert count_cohort_members(self.team.id, other_cohort.id) == 0
        get_active_fake().assert_not_called("count_cohort_members")


class TestInsertUsersListWithBatchingPersonhog(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _create_static_cohort(self) -> Cohort:
        return Cohort.objects.create(team=self.team, groups=[], is_static=True, name="test cohort")

    @patch("products.cohorts.backend.models.util.insert_static_cohort")
    def test_insert_users_by_uuid(self, mock_insert_ch):
        p1 = create_person(team=self.team, distinct_ids=["d1"])
        p2 = create_person(team=self.team, distinct_ids=["d2"])
        cohort = self._create_static_cohort()

        cohort.insert_users_list_by_uuid([str(p1.uuid), str(p2.uuid)], team_id=self.team.id)

        get_active_fake().assert_called("insert_cohort_members")

    @patch("products.cohorts.backend.models.util.insert_static_cohort")
    def test_insert_users_by_distinct_id(self, mock_insert_ch):
        create_person(team=self.team, distinct_ids=["d1"])
        create_person(team=self.team, distinct_ids=["d2"])
        cohort = self._create_static_cohort()

        cohort.insert_users_by_list(["d1", "d2"], team_id=self.team.id)

        get_active_fake().assert_called("insert_cohort_members")

    @patch("products.cohorts.backend.models.util.insert_static_cohort")
    def test_insert_idempotent(self, mock_insert_ch):
        person = create_person(team=self.team, distinct_ids=["d1"])
        cohort = self._create_static_cohort()

        cohort.insert_users_list_by_uuid([str(person.uuid)], team_id=self.team.id)
        cohort.insert_users_list_by_uuid([str(person.uuid)], team_id=self.team.id)
