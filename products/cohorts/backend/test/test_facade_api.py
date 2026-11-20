from datetime import timedelta
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin, flush_persons_and_events

from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.models.person.sql import PERSON_STATIC_COHORT_TABLE, REPLACE_ROW_OFFSET, static_cohort_membership_filter
from posthog.models.team import Team
from posthog.test.persons import add_cohort_members, create_person

from products.cohorts.backend.facade.api import cohort_exists_for_team, replace_static_cohort_members
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import list_cohort_member_ids


class TestCohortExistsForTeam(BaseTest):
    def test_a_cohort_is_only_visible_to_its_own_team(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Churn risk")
        other_team = Team.objects.create(organization=self.organization, name="Other")

        assert cohort_exists_for_team(team_id=self.team.id, cohort_id=cohort.id)
        assert not cohort_exists_for_team(team_id=other_team.id, cohort_id=cohort.id)

    def test_a_soft_deleted_cohort_still_counts(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Churn risk", deleted=True)

        assert cohort_exists_for_team(team_id=self.team.id, cohort_id=cohort.id)


class TestReplaceStaticCohortMembers(ClickhouseTestMixin, BaseTest):
    def test_a_contact_fill_after_a_finished_replace_counts_its_adds_and_removes_from_both_stores(self) -> None:
        people = {
            name: create_person(team=self.team, distinct_ids=[f"user-{name}"], uuid=uuid4())
            for name in ("ada", "bea", "cy")
        }
        flush_persons_and_events()
        cohort = Cohort.objects.create(team=self.team, name="Contacts", is_static=True)
        # Ada and Bea are the members a finished replace kept, so their rows sit at its marker.
        marker = timezone.now().replace(microsecond=0) - timedelta(hours=1)
        Cohort.objects.filter(pk=cohort.pk).update(
            last_replace_marker=marker, last_replace_floor=marker - timedelta(minutes=1)
        )
        sync_execute(
            f"INSERT INTO {PERSON_STATIC_COHORT_TABLE} (id, person_id, cohort_id, team_id, _timestamp, _offset) VALUES",
            [
                (uuid4(), people[name].uuid, cohort.pk, self.team.pk, marker, REPLACE_ROW_OFFSET)
                for name in ("ada", "bea")
            ],
        )
        add_cohort_members(cohort, [people["ada"], people["bea"]])

        replaced = replace_static_cohort_members(
            team_id=self.team.pk, cohort_id=cohort.pk, distinct_ids=["user-ada", "user-cy"]
        )

        cohort.refresh_from_db()
        membership_sql, membership_params = static_cohort_membership_filter(
            cohort.last_replace_marker, cohort.last_replace_floor
        )
        # The rows ClickHouse readers count as membership after that replace.
        counted = sync_execute(
            f"SELECT DISTINCT person_id FROM {PERSON_STATIC_COHORT_TABLE} WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s AND {membership_sql}",
            {"team_id": self.team.pk, "cohort_id": cohort.pk, **membership_params},
        )
        bea_rows = sync_execute(
            f"SELECT count() FROM {PERSON_STATIC_COHORT_TABLE} WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s AND person_id = %(person_id)s",
            {"team_id": self.team.pk, "cohort_id": cohort.pk, "person_id": str(people["bea"].uuid)},
        )
        assert replaced.removed == 1
        assert {str(row[0]) for row in counted} == {str(people["ada"].uuid), str(people["cy"].uuid)}
        assert bea_rows[0][0] == 0
        assert set(list_cohort_member_ids(self.team.pk, cohort.pk)) == {people["ada"].id, people["cy"].id}
        assert cohort.count == 2
