from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.models import Person
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
)


class TestCohortPeopleTable(ClickhouseTestMixin, APIBaseTest):
    def test_optimize_query(self):
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

        response = execute_hogql_query(
            parse_select("select id from persons where properties.$some_prop = 'something'"),
            self.team,
        )
        assert (
            response.clickhouse
            == """SELECT
    persons.id AS id
FROM
    (SELECT
        person.id AS id,
        replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS `properties___$some_prop`
    FROM
        person
    WHERE
        and(equals(person.team_id, {team_id}), in(person.id, (SELECT
                    person.id AS id
                FROM
                    person
                WHERE
                    and(equals(person.team_id, {team_id}), ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_1)s), ''), 'null'), '^"|"$', ''), %(hogql_val_2)s), 0)))))
    GROUP BY
        person.id,
        `properties___$some_prop`
    HAVING
        and(ifNull(equals(argMax(person.is_deleted, person.version), 0), 0), ifNull(less(argMax(toTimeZone(person.created_at, %(hogql_val_3)s), person.version), plus(now64(6, %(hogql_val_4)s), toIntervalDay(1))), 0))
    SETTINGS optimize_aggregation_in_order=1) AS persons
WHERE
    ifNull(equals(persons.`properties___$some_prop`, %(hogql_val_5)s), 0)
LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0""".format(
                team_id=self.team.pk
            )
        )
        assert len(response.results) == 2

        response = execute_hogql_query(
            parse_select("select id, properties.email from persons"),
            self.team,
        )

        assert (
            response.clickhouse
            == """SELECT
    persons.id AS id,
    persons.properties___email AS email
FROM
    (SELECT
        person.id AS id,
        replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '') AS properties___email
    FROM
        person
    WHERE
        equals(person.team_id, {team_id})
    GROUP BY
        person.id,
        properties___email
    HAVING
        and(ifNull(equals(argMax(person.is_deleted, person.version), 0), 0), ifNull(less(argMax(toTimeZone(person.created_at, %(hogql_val_1)s), person.version), plus(now64(6, %(hogql_val_2)s), toIntervalDay(1))), 0))
    SETTINGS optimize_aggregation_in_order=1) AS persons
LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0""".format(
                team_id=self.team.pk
            )
        )
