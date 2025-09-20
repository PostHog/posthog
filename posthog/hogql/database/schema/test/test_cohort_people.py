from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Cohort, Person


class TestCohortPeopleTable(ClickhouseTestMixin, APIBaseTest):
    def test_select_star(self):
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "$another_prop": "something1"},
        )
        Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["2"],
            properties={"$some_prop": "something", "$another_prop": "something2"},
        )
        Person.objects.create(
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
        Person.objects.create(
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
