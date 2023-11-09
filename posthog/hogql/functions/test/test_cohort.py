from django.test import override_settings

from posthog.hogql import ast
from posthog.hogql.errors import HogQLException
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.models import Cohort
from posthog.models.cohort.util import recalculate_cohortpeople
from posthog.models.utils import UUIDT
from posthog.schema import HogQLQueryModifiers
from posthog.test.base import (
    BaseTest,
    _create_person,
    _create_event,
    flush_persons_and_events,
)

elements_chain_match = lambda x: parse_expr("match(elements_chain, {regex})", {"regex": ast.Constant(value=str(x))})
not_call = lambda x: ast.Call(name="not", args=[x])


class TestCohort(BaseTest):
    maxDiff = None

    def _create_random_events(self) -> str:
        random_uuid = str(UUIDT())
        _create_person(
            properties={"$os": "Chrome", "random_uuid": random_uuid},
            team=self.team,
            distinct_ids=["bla"],
            is_identified=True,
        )
        _create_event(distinct_id="bla", event=random_uuid, team=self.team)
        flush_persons_and_events()
        return random_uuid

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_in_cohort_dynamic(self):
        random_uuid = self._create_random_events()
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$os", "value": "Chrome", "type": "person"}]}],
        )
        recalculate_cohortpeople(cohort, pending_version=0)
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE person_id IN COHORT {cohort.pk} AND event='{random_uuid}'",
            self.team,
            modifiers=HogQLQueryModifiers(inCohortVia="subquery"),
        )
        self.assertEqual(
            response.clickhouse,
            f"SELECT events.event FROM events WHERE and(equals(events.team_id, {self.team.pk}), in(events.person_id, (SELECT cohortpeople.person_id FROM cohortpeople WHERE and(equals(cohortpeople.team_id, {self.team.pk}), equals(cohortpeople.cohort_id, {cohort.pk})) GROUP BY cohortpeople.person_id, cohortpeople.cohort_id, cohortpeople.version HAVING ifNull(greater(sum(cohortpeople.sign), 0), 0))), equals(events.event, %(hogql_val_0)s)) LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1",
        )
        self.assertEqual(
            response.hogql,
            f"SELECT event FROM events WHERE and(in(person_id, (SELECT person_id FROM raw_cohort_people WHERE equals(cohort_id, {cohort.pk}) GROUP BY person_id, cohort_id, version HAVING greater(sum(sign), 0))), equals(event, '{random_uuid}')) LIMIT 100",
        )
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0][0], random_uuid)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_in_cohort_static(self):
        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
        )
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE person_id IN COHORT {cohort.pk}",
            self.team,
            modifiers=HogQLQueryModifiers(inCohortVia="subquery"),
        )
        self.assertEqual(
            response.clickhouse,
            f"SELECT events.event FROM events WHERE and(equals(events.team_id, {self.team.pk}), in(events.person_id, (SELECT person_static_cohort.person_id FROM person_static_cohort WHERE and(equals(person_static_cohort.team_id, {self.team.pk}), equals(person_static_cohort.cohort_id, {cohort.pk}))))) LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1",
        )
        self.assertEqual(
            response.hogql,
            f"SELECT event FROM events WHERE in(person_id, (SELECT person_id FROM static_cohort_people WHERE equals(cohort_id, {cohort.pk}))) LIMIT 100",
        )

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_in_cohort_strings(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="my cohort",
            is_static=True,
        )
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE person_id IN COHORT 'my cohort'",
            self.team,
            modifiers=HogQLQueryModifiers(inCohortVia="subquery"),
        )
        self.assertEqual(
            response.clickhouse,
            f"SELECT events.event FROM events WHERE and(equals(events.team_id, {self.team.pk}), in(events.person_id, (SELECT person_static_cohort.person_id FROM person_static_cohort WHERE and(equals(person_static_cohort.team_id, {self.team.pk}), equals(person_static_cohort.cohort_id, {cohort.pk}))))) LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1",
        )
        self.assertEqual(
            response.hogql,
            f"SELECT event FROM events WHERE in(person_id, (SELECT person_id FROM static_cohort_people WHERE equals(cohort_id, {cohort.pk}))) LIMIT 100",
        )

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_in_cohort_error(self):
        with self.assertRaises(HogQLException) as e:
            execute_hogql_query(f"SELECT event FROM events WHERE person_id IN COHORT true", self.team)
        self.assertEqual(str(e.exception), "cohort() takes exactly one string or integer argument")

        with self.assertRaises(HogQLException) as e:
            execute_hogql_query(
                f"SELECT event FROM events WHERE person_id IN COHORT 'blabla'",
                self.team,
            )
        self.assertEqual(str(e.exception), "Could not find a cohort with the name 'blabla'")
