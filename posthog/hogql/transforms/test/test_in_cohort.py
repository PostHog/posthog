import pytest
from posthog.test.base import BaseTest, QueryMatchingTest, _create_event, _create_person

from django.test import override_settings

from posthog.schema import HogQLQueryModifiers, InCohortVia, InlineCohortCalculation

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_response_in_tests

from posthog.clickhouse.client.execute import sync_execute
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


class TestInlineCohortLeftjoin(QueryMatchingTest, BaseTest):
    maxDiff = None

    def _setup_cohort_with_new_person_after_calculation(self):
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        distinct_id1 = f"p1_{random_uuid}"
        distinct_id2 = f"p2_{random_uuid}"
        _create_person(
            properties={"test_prop": random_uuid},
            team=self.team,
            distinct_ids=[distinct_id1],
            is_identified=True,
        )
        _create_event(distinct_id=distinct_id1, event=random_uuid, team=self.team)

        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "test_prop", "value": random_uuid, "type": "person"}]}],
        )
        recalculate_cohortpeople(cohort, pending_version=0, initiating_user_id=None)

        _create_person(
            properties={"test_prop": random_uuid},
            team=self.team,
            distinct_ids=[distinct_id2],
            is_identified=True,
        )
        _create_event(distinct_id=distinct_id2, event=random_uuid, team=self.team)
        sync_execute("OPTIMIZE TABLE person FINAL")

        return cohort, random_uuid

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_inline_leftjoin_off_vs_always(self):
        cohort, random_uuid = self._setup_cohort_with_new_person_after_calculation()
        query = f"SELECT event FROM events WHERE person_id IN COHORT {cohort.pk} AND event = '{random_uuid}'"

        off_response = execute_hogql_query(
            query,
            self.team,
            modifiers=HogQLQueryModifiers(
                inCohortVia=InCohortVia.LEFTJOIN, inlineCohortCalculation=InlineCohortCalculation.OFF
            ),
            pretty=False,
        )
        assert len(off_response.results or []) == 1
        assert pretty_print_response_in_tests(off_response, self.team.pk) == self.snapshot

        always_response = execute_hogql_query(
            query,
            self.team,
            modifiers=HogQLQueryModifiers(
                inCohortVia=InCohortVia.LEFTJOIN, inlineCohortCalculation=InlineCohortCalculation.ALWAYS
            ),
            pretty=False,
        )
        assert len(always_response.results or []) == 2
        assert pretty_print_response_in_tests(always_response, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_inline_conjoined_off_vs_always(self):
        cohort, random_uuid = self._setup_cohort_with_new_person_after_calculation()
        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "test_prop", "value": random_uuid, "type": "person"}]}],
        )
        recalculate_cohortpeople(cohort2, pending_version=0, initiating_user_id=None)
        query = f"SELECT event FROM events WHERE (person_id IN COHORT {cohort.pk} OR person_id IN COHORT {cohort2.pk}) AND event = '{random_uuid}'"

        off_response = execute_hogql_query(
            query,
            self.team,
            modifiers=HogQLQueryModifiers(
                inCohortVia=InCohortVia.LEFTJOIN_CONJOINED, inlineCohortCalculation=InlineCohortCalculation.OFF
            ),
            pretty=False,
        )
        # person1 matches both cohorts (2 rows) + person2 matches only cohort2 (1 row) = 3
        assert len(off_response.results or []) == 3
        assert pretty_print_response_in_tests(off_response, self.team.pk) == self.snapshot

        always_response = execute_hogql_query(
            query,
            self.team,
            modifiers=HogQLQueryModifiers(
                inCohortVia=InCohortVia.LEFTJOIN_CONJOINED, inlineCohortCalculation=InlineCohortCalculation.ALWAYS
            ),
            pretty=False,
        )
        # both persons match both cohorts inline: 2 persons × 2 cohorts = 4
        assert len(always_response.results or []) == 4
        assert pretty_print_response_in_tests(always_response, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_inline_conjoined_mixed_static_and_dynamic(self):
        cohort, random_uuid = self._setup_cohort_with_new_person_after_calculation()
        static_cohort = Cohort.objects.create(team=self.team, is_static=True)
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE (person_id IN COHORT {cohort.pk} OR person_id IN COHORT {static_cohort.pk}) AND event = '{random_uuid}'",
            self.team,
            modifiers=HogQLQueryModifiers(
                inCohortVia=InCohortVia.LEFTJOIN_CONJOINED, inlineCohortCalculation=InlineCohortCalculation.ALWAYS
            ),
            pretty=False,
        )
        assert len(response.results or []) == 2
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_inline_static_always_uses_cohortpeople(self):
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        _create_person(
            properties={"$os": "Chrome"},
            team=self.team,
            distinct_ids=["person1"],
            is_identified=True,
        )
        _create_event(distinct_id="person1", event=random_uuid, team=self.team)

        cohort = Cohort.objects.create(team=self.team, is_static=True)
        cohort.insert_users_by_list(["person1"])
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE person_id IN COHORT {cohort.pk} AND event = '{random_uuid}'",
            self.team,
            modifiers=HogQLQueryModifiers(
                inCohortVia=InCohortVia.LEFTJOIN, inlineCohortCalculation=InlineCohortCalculation.ALWAYS
            ),
            pretty=False,
        )
        assert len(response.results or []) == 1
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
