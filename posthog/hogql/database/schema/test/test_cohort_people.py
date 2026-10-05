from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.test.persons import create_person

from products.cohorts.backend.models.cohort import Cohort


class TestCohortPeopleTable(ClickhouseTestMixin, APIBaseTest):
    def test_select_star(self):
        create_person(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "$another_prop": "something1"},
        )
        create_person(
            team_id=self.team.pk,
            distinct_ids=["2"],
            properties={"$some_prop": "something", "$another_prop": "something2"},
        )
        create_person(
            team_id=self.team.pk,
            distinct_ids=["3"],
            properties={"$some_prop": "not something", "$another_prop": "something3"},
        )
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {"key": "$some_prop", "value": "something", "type": "person"},
                    ]
                }
            ],
            name="cohort1",
        )
        cohort1.calculate_people_ch(pending_version=0)
        cohort1.calculate_people_ch(pending_version=2)
        cohort1.calculate_people_ch(pending_version=4)

        response = execute_hogql_query(
            parse_select(
                "select *, person.properties.$another_prop from cohort_people order by person.properties.$another_prop"
            ),
            self.team,
        )
        assert response.columns == ["person_id", "cohort_id", "$another_prop"]
        assert response.results is not None
        assert len(response.results) == 2
        assert response.results[0][2] == "something1"
        assert response.results[1][2] == "something2"

    def test_empty_version(self):
        create_person(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "$another_prop": "something1"},
        )
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {"key": "$some_prop", "value": "something", "type": "person"},
                    ]
                }
            ],
            name="cohort1",
        )
        response = execute_hogql_query(
            parse_select(
                "select *, person.properties.$another_prop from cohort_people order by person.properties.$another_prop"
            ),
            self.team,
        )
        # never calculated, version empty
        assert response.columns == ["person_id", "cohort_id", "$another_prop"]
        assert response.results is not None
        assert len(response.results) == 0
        assert cohort1.version is None

    def test_cohort_membership_serves_current_cohort_people_members(self):
        for distinct_id, prop in (("1", "something"), ("2", "something"), ("3", "not something")):
            create_person(team_id=self.team.pk, distinct_ids=[distinct_id], properties={"$some_prop": prop})
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )
        cohort.calculate_people_ch(pending_version=0)

        members = execute_hogql_query(
            f"SELECT person_id FROM cohort_people WHERE cohort_id = {cohort.pk} ORDER BY person_id", self.team
        ).results
        # The shape saved queries used against the removed realtime table.
        legacy_name = execute_hogql_query(
            f"SELECT cohort_membership.person_id FROM cohort_membership WHERE cohort_id = {cohort.pk} ORDER BY person_id",
            self.team,
        ).results

        # Unaliased, the lazy-table pass keys each table by its printed name, so the two names must not collide.
        both_names = execute_hogql_query(
            f"""
            SELECT cohort_membership.person_id FROM cohort_membership
            JOIN cohort_people ON cohort_people.person_id = cohort_membership.person_id
                AND cohort_people.cohort_id = cohort_membership.cohort_id
            WHERE cohort_membership.cohort_id = {cohort.pk} ORDER BY cohort_membership.person_id
            """,
            self.team,
        ).results
        qualified_name = execute_hogql_query(
            f"SELECT person_id FROM posthog.cohort_membership WHERE cohort_id = {cohort.pk} ORDER BY person_id",
            self.team,
        ).results

        assert members is not None and len(members) == 2
        assert legacy_name == members
        assert both_names == members
        assert qualified_name == members

        padded_uuid_filter = execute_hogql_query(
            f"SELECT person_id FROM cohort_membership WHERE cohort_id = {cohort.pk} AND person_id = ' {members[0][0]} '",
            self.team,
        ).results
        assert padded_uuid_filter == [members[0]]
