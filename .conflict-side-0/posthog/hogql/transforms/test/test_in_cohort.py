import pytest
from posthog.test.base import BaseTest, _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from posthog.schema import HogQLQueryModifiers, InCohortVia

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_response_in_tests

from posthog.models import Cohort
from posthog.models.cohort.util import recalculate_cohortpeople
from posthog.models.utils import UUIDT

elements_chain_match = lambda x: parse_expr("match(elements_chain, {regex})", {"regex": ast.Constant(value=str(x))})
not_call = lambda x: ast.Call(name="not", args=[x])


class TestInCohort(BaseTest):
    maxDiff = None

    def _create_random_events(self) -> str:
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        _create_person(
            properties={"$os": "Chrome", "random_uuid": random_uuid},
            team=self.team,
            distinct_ids=["bla"],
            is_identified=True,
        )
        _create_event(distinct_id="bla", event=random_uuid, team=self.team)
        flush_persons_and_events()
        return random_uuid

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_in_cohort_dynamic(self):
        random_uuid = self._create_random_events()
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$os", "value": "Chrome", "type": "person"}]}],
        )
        recalculate_cohortpeople(cohort, pending_version=0, initiating_user_id=None)
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE person_id IN COHORT {cohort.pk} AND event='{random_uuid}'",
            self.team,
            modifiers=HogQLQueryModifiers(inCohortVia=InCohortVia.LEFTJOIN),
            pretty=False,
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot  # type: ignore
        self.assertEqual(len(response.results or []), 1)
        self.assertEqual((response.results or [])[0][0], random_uuid)

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_in_cohort_static(self):
        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
        )
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE person_id IN COHORT {cohort.pk}",
            self.team,
            modifiers=HogQLQueryModifiers(inCohortVia=InCohortVia.LEFTJOIN),
            pretty=False,
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot  # type: ignore

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_in_cohort_strings(self):
        Cohort.objects.create(
            team=self.team,
            name="my cohort",
            is_static=True,
        )
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE person_id IN COHORT 'my cohort'",
            self.team,
            modifiers=HogQLQueryModifiers(inCohortVia=InCohortVia.LEFTJOIN),
            pretty=False,
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot  # type: ignore

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_in_cohort_deleted(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="my cohort",
            is_static=True,
        )
        cohort.deleted = True
        cohort.save()

        Cohort.objects.create(
            team=self.team,
            name="my cohort",
            is_static=True,
        )

        response = execute_hogql_query(
            f"SELECT event FROM events WHERE person_id IN COHORT 'my cohort'",
            self.team,
            modifiers=HogQLQueryModifiers(inCohortVia=InCohortVia.LEFTJOIN),
            pretty=False,
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot  # type: ignore

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_in_cohort_error(self):
        with self.assertRaises(QueryError) as e:
            execute_hogql_query(
                f"SELECT event FROM events WHERE person_id IN COHORT true",
                self.team,
                modifiers=HogQLQueryModifiers(inCohortVia=InCohortVia.SUBQUERY),
                pretty=False,
            )
        self.assertEqual(str(e.exception), "cohort() takes exactly one string or integer argument")

        with self.assertRaises(QueryError) as e:
            execute_hogql_query(
                f"SELECT event FROM events WHERE person_id IN COHORT 'blabla'",
                self.team,
                modifiers=HogQLQueryModifiers(inCohortVia=InCohortVia.SUBQUERY),
                pretty=False,
            )
        self.assertEqual(str(e.exception), "Could not find a cohort with the name 'blabla'")

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_in_cohort_conjoined_string(self):
        Cohort.objects.create(
            team=self.team,
            name="my cohort",
            is_static=True,
        )
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE person_id IN COHORT 'my cohort'",
            self.team,
            modifiers=HogQLQueryModifiers(inCohortVia=InCohortVia.LEFTJOIN_CONJOINED),
            pretty=False,
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot  # type: ignore

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_in_cohort_conjoined_int(self):
        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
        )
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE person_id IN COHORT {cohort.pk}",
            self.team,
            modifiers=HogQLQueryModifiers(inCohortVia=InCohortVia.LEFTJOIN_CONJOINED),
            pretty=False,
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot  # type: ignore

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_in_cohort_conjoined_dynamic(self):
        random_uuid = self._create_random_events()
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$os", "value": "Chrome", "type": "person"}]}],
        )
        recalculate_cohortpeople(cohort, pending_version=0, initiating_user_id=None)
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE person_id IN COHORT {cohort.pk} AND event='{random_uuid}'",
            self.team,
            modifiers=HogQLQueryModifiers(inCohortVia=InCohortVia.LEFTJOIN_CONJOINED),
            pretty=False,
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot  # type: ignore
        self.assertEqual(len(response.results or []), 1)
        self.assertEqual((response.results or [])[0][0], random_uuid)

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_in_cohort_conjoined_error(self):
        with self.assertRaises(QueryError) as e:
            execute_hogql_query(
                f"SELECT event FROM events WHERE person_id IN COHORT true",
                self.team,
                modifiers=HogQLQueryModifiers(inCohortVia=InCohortVia.LEFTJOIN_CONJOINED),
                pretty=False,
            )
        self.assertEqual(str(e.exception), "cohort() takes exactly one string or integer argument")

        with self.assertRaises(QueryError) as e:
            execute_hogql_query(
                f"SELECT event FROM events WHERE person_id IN COHORT 'blabla'",
                self.team,
                modifiers=HogQLQueryModifiers(inCohortVia=InCohortVia.LEFTJOIN_CONJOINED),
                pretty=False,
            )
        self.assertEqual(str(e.exception), "Could not find a cohort with the name 'blabla'")
