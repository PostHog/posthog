import datetime

import pytest
from posthog.test.base import BaseTest, _create_event, _create_person
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from posthog.schema import HogQLQueryModifiers, InlineCohortCalculation

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_response_in_tests

from posthog.clickhouse.client.execute import sync_execute
from posthog.models import Cohort
from posthog.models.cohort.calculation_history import CohortCalculationHistory
from posthog.models.cohort.util import recalculate_cohortpeople
from posthog.models.team.team import Team
from posthog.models.utils import UUIDT

elements_chain_match = lambda x: parse_expr("match(elements_chain, {regex})", {"regex": ast.Constant(value=str(x))})
not_call = lambda x: ast.Call(name="not", args=[x])


class TestCohort(BaseTest):
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
            modifiers=HogQLQueryModifiers(inCohortVia="subquery"),
            pretty=False,
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot  # type: ignore
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0][0], random_uuid)

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_in_cohort_dynamic_other_team_in_project(self):
        random_uuid = self._create_random_events()
        other_team_in_project = Team.objects.create(organization=self.organization, project=self.project)
        cohort = Cohort.objects.create(
            team=other_team_in_project,  # Not self.team!
            groups=[{"properties": [{"key": "$os", "value": "Chrome", "type": "person"}]}],
        )
        recalculate_cohortpeople(cohort, pending_version=0, initiating_user_id=None)
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE person_id IN COHORT {cohort.pk} AND event='{random_uuid}'",
            self.team,
            modifiers=HogQLQueryModifiers(inCohortVia="subquery"),
            pretty=False,
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot  # type: ignore
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0][0], random_uuid)

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
            modifiers=HogQLQueryModifiers(inCohortVia="subquery"),
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
            modifiers=HogQLQueryModifiers(inCohortVia="subquery"),
            pretty=False,
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot  # type: ignore

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_in_cohort_error(self):
        with self.assertRaises(QueryError) as e:
            execute_hogql_query(f"SELECT event FROM events WHERE person_id IN COHORT true", self.team)
        self.assertEqual(str(e.exception), "cohort() takes exactly one string or integer argument")

        with self.assertRaises(QueryError) as e:
            execute_hogql_query(
                f"SELECT event FROM events WHERE person_id IN COHORT 'blabla'",
                self.team,
            )
        self.assertEqual(str(e.exception), "Could not find a cohort with the name 'blabla'")


class TestInlineCohortSubquery(BaseTest):
    """Tests for inlineCohortCalculation modifier via the subquery (cohort()) path."""

    def _setup_cohort_with_new_person_after_calculation(self):
        """Create a cohort, calculate it, then add a new person who matches but isn't in cohortpeople."""
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

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_inline_cohort_subquery_off_vs_always(self):
        cohort, random_uuid = self._setup_cohort_with_new_person_after_calculation()
        query = f"SELECT event FROM events WHERE person_id IN COHORT {cohort.pk} AND event = '{random_uuid}'"

        off_response = execute_hogql_query(
            query,
            self.team,
            modifiers=HogQLQueryModifiers(inCohortVia="subquery", inlineCohortCalculation=InlineCohortCalculation.OFF),
            pretty=False,
        )
        self.assertEqual(len(off_response.results), 1)

        always_response = execute_hogql_query(
            query,
            self.team,
            modifiers=HogQLQueryModifiers(
                inCohortVia="subquery", inlineCohortCalculation=InlineCohortCalculation.ALWAYS
            ),
            pretty=False,
        )
        self.assertEqual(len(always_response.results), 2)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_inline_cohort_static_always_uses_cohortpeople(self):
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
                inCohortVia="subquery", inlineCohortCalculation=InlineCohortCalculation.ALWAYS
            ),
            pretty=False,
        )
        self.assertEqual(len(response.results), 1)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_inline_cohort_auto_mode_with_fast_history(self):
        cohort, random_uuid = self._setup_cohort_with_new_person_after_calculation()
        now = timezone.now()
        CohortCalculationHistory.objects.create(
            team=self.team,
            cohort=cohort,
            filters={},
            started_at=now,
            finished_at=now,
        )
        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = execute_hogql_query(
                f"SELECT event FROM events WHERE person_id IN COHORT {cohort.pk} AND event = '{random_uuid}'",
                self.team,
                modifiers=HogQLQueryModifiers(
                    inCohortVia="subquery", inlineCohortCalculation=InlineCohortCalculation.AUTO
                ),
                pretty=False,
            )
        self.assertEqual(len(response.results), 2)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_inline_cohort_auto_mode_newest_calc_failed(self):
        cohort, random_uuid = self._setup_cohort_with_new_person_after_calculation()
        now = timezone.now()
        CohortCalculationHistory.objects.create(
            team=self.team,
            cohort=cohort,
            filters={},
            started_at=now - datetime.timedelta(hours=2),
            finished_at=now - datetime.timedelta(hours=2),
        )
        CohortCalculationHistory.objects.create(
            team=self.team,
            cohort=cohort,
            filters={},
            started_at=now,
            finished_at=now,
            error="timeout",
        )
        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = execute_hogql_query(
                f"SELECT event FROM events WHERE person_id IN COHORT {cohort.pk} AND event = '{random_uuid}'",
                self.team,
                modifiers=HogQLQueryModifiers(
                    inCohortVia="subquery", inlineCohortCalculation=InlineCohortCalculation.AUTO
                ),
                pretty=False,
            )
        self.assertEqual(len(response.results), 1)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_inline_cohort_auto_mode_flag_disabled(self):
        cohort, random_uuid = self._setup_cohort_with_new_person_after_calculation()
        with patch("posthoganalytics.feature_enabled", return_value=False):
            response = execute_hogql_query(
                f"SELECT event FROM events WHERE person_id IN COHORT {cohort.pk} AND event = '{random_uuid}'",
                self.team,
                modifiers=HogQLQueryModifiers(
                    inCohortVia="subquery", inlineCohortCalculation=InlineCohortCalculation.AUTO
                ),
                pretty=False,
            )
        self.assertEqual(len(response.results), 1)
