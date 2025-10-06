import uuid
from datetime import datetime
from typing import Any, cast

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    create_person_id_override_by_distinct_id,
    snapshot_clickhouse_queries,
)
from unittest.mock import Mock, patch

from django.test import override_settings

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    ActorsQuery,
    BaseMathType,
    BreakdownFilter,
    BreakdownType,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    FunnelConversionWindowTimeUnit,
    FunnelExclusionEventsNode,
    FunnelMathType,
    FunnelsActorsQuery,
    FunnelsFilter,
    FunnelsQuery,
    GroupPropertyFilter,
    HogQLQueryModifiers,
    IntervalType,
    PersonsOnEventsMode,
    PropertyOperator,
)

from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import execute_hogql_query

from posthog.api.instance_settings import get_instance_setting
from posthog.clickhouse.client.execute import sync_execute
from posthog.constants import INSIGHT_FUNNELS, FunnelOrderType, FunnelVizType
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.insights.funnels import Funnel
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.funnels.test.breakdown_cases import (
    assert_funnel_results_equal,
    funnel_breakdown_group_test_factory,
    funnel_breakdown_test_factory,
)
from posthog.hogql_queries.insights.funnels.test.conversion_time_cases import funnel_conversion_time_test_factory
from posthog.hogql_queries.insights.funnels.test.test_funnel_persons import get_actors
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.models import Action, Element, Team
from posthog.models.cohort.cohort import Cohort
from posthog.models.group.util import create_group
from posthog.models.property_definition import PropertyDefinition
from posthog.test.test_journeys import journeys_for
from posthog.test.test_utils import create_group_type_mapping_without_created_at


class PseudoFunnelActors:
    def __init__(self, person_filter: Any, team: Team):
        self.filters = person_filter._data
        self.team = team

    def get_actors(self):
        actors = get_actors(
            self.filters,
            self.team,
            funnel_step=self.filters.get("funnel_step"),
            funnel_step_breakdown=self.filters.get("funnel_step_breakdown"),
        )

        return (
            None,
            [{"id": x[0]} for x in actors],
            None,
        )


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": name, "properties": properties}])
    return action


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=False))
class TestFunnelBreakdown(
    ClickhouseTestMixin,
    funnel_breakdown_test_factory(  # type: ignore
        FunnelOrderType.ORDERED,
        PseudoFunnelActors,
        _create_action,
        _create_person,
    ),
):
    maxDiff = None
    pass


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=False))
class TestFunnelGroupBreakdown(
    ClickhouseTestMixin,
    funnel_breakdown_group_test_factory(  # type: ignore
        FunnelOrderType.ORDERED,
        PseudoFunnelActors,
    ),
):
    pass


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=False))
class TestFunnelConversionTime(
    ClickhouseTestMixin,
    funnel_conversion_time_test_factory(FunnelOrderType.ORDERED, PseudoFunnelActors),  # type: ignore
):
    maxDiff = None
    pass


def funnel_test_factory(Funnel, event_factory, person_factory):
    class TestGetFunnel(ClickhouseTestMixin, APIBaseTest):
        def _get_actor_ids_at_step(self, filters, funnelStep, funnelStepBreakdown=None):
            funnels_query = cast(FunnelsQuery, filter_to_query(filters))
            funnel_actors_query = FunnelsActorsQuery(
                source=funnels_query, funnelStep=funnelStep, funnelStepBreakdown=funnelStepBreakdown
            )
            actors_query = ActorsQuery(source=funnel_actors_query)
            response = ActorsQueryRunner(query=actors_query, team=self.team).calculate()
            return [val[0]["id"] for val in response.results]

        def _signup_event(self, **kwargs):
            event_factory(team=self.team, event="user signed up", **kwargs)

        def _add_to_cart_event(self, **kwargs):
            event_factory(team=self.team, event="added to cart", **kwargs)

        def _checkout_event(self, **kwargs):
            event_factory(team=self.team, event="checked out", **kwargs)

        def _pay_event(self, **kwargs):
            event_factory(
                team=self.team,
                event="$autocapture",
                elements=[Element(nth_of_type=1, nth_child=0, tag_name="button", text="Pay $10")],
                **kwargs,
            )

        def _movie_event(self, **kwargs):
            event_factory(
                team=self.team,
                event="$autocapture",
                elements=[Element(nth_of_type=1, nth_child=0, tag_name="a", href="/movie")],
                **kwargs,
            )

        def _create_groups(self):
            create_group_type_mapping_without_created_at(
                team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
            )
            create_group_type_mapping_without_created_at(
                team=self.team, project_id=self.team.project_id, group_type="company", group_type_index=1
            )

            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key="org:5",
                properties={"industry": "finance"},
            )
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key="org:6",
                properties={"industry": "technology"},
            )

            create_group(
                team_id=self.team.pk,
                group_type_index=1,
                group_key="company:1",
                properties={},
            )
            create_group(
                team_id=self.team.pk,
                group_type_index=1,
                group_key="company:2",
                properties={},
            )

        def _basic_funnel(self, properties=None, filters=None):
            action_credit_card = Action.objects.create(
                team=self.team,
                name="paid",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "tag_name": "button",
                        "text": "Pay $10",
                    }
                ],
            )
            action_play_movie = Action.objects.create(
                team=self.team,
                name="watched movie",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "tag_name": "a",
                        "href": "/movie",
                    }
                ],
            )

            if filters is None:
                filters = {
                    "events": [{"id": "user signed up", "type": "events", "order": 0}],
                    "actions": [
                        {"id": action_credit_card.pk, "type": "actions", "order": 1},
                        {"id": action_play_movie.pk, "type": "actions", "order": 2},
                    ],
                    "funnel_window_days": 14,
                }

            if properties is not None:
                filters.update({"properties": properties})

            filters["insight"] = INSIGHT_FUNNELS

            query = cast(FunnelsQuery, filter_to_query(filters))
            return FunnelsQueryRunner(query=query, team=self.team)

        def test_funnel_events(self):
            funnel = self._basic_funnel()

            # events
            person_factory(distinct_ids=["stopped_after_signup"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_signup")

            person_factory(distinct_ids=["stopped_after_pay"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_pay")
            self._pay_event(distinct_id="stopped_after_pay")

            person_factory(
                distinct_ids=["had_anonymous_id", "completed_movie"],
                team_id=self.team.pk,
            )
            self._signup_event(distinct_id="had_anonymous_id")
            self._pay_event(distinct_id="completed_movie")
            self._movie_event(distinct_id="completed_movie")

            person_factory(distinct_ids=["just_did_movie"], team_id=self.team.pk)
            self._movie_event(distinct_id="just_did_movie")

            person_factory(distinct_ids=["wrong_order"], team_id=self.team.pk)
            self._pay_event(distinct_id="wrong_order")
            self._signup_event(distinct_id="wrong_order")
            self._movie_event(distinct_id="wrong_order")

            result = funnel.calculate().results
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 4)

            self.assertEqual(result[1]["name"], "paid")
            self.assertEqual(result[1]["count"], 2)
            self.assertEqual(result[2]["name"], "watched movie")
            self.assertEqual(result[2]["count"], 1)

        @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True)
        @snapshot_clickhouse_queries
        def test_funnel_events_with_person_on_events_v2(self):
            # KLUDGE: We need to do this to ensure create_person_id_override_by_distinct_id
            # works correctly. Worth considering other approaches as we generally like to
            # avoid truncating tables in tests for speed.
            sync_execute("TRUNCATE TABLE sharded_events")
            with freeze_time("2012-01-01T03:21:34.000Z"):
                funnel = self._basic_funnel()

            with freeze_time("2012-01-01T03:21:35.000Z"):
                # events
                stopped_after_signup_person_id = uuid.uuid4()
                person_factory(distinct_ids=["stopped_after_signup"], team_id=self.team.pk)
                self._signup_event(
                    distinct_id="stopped_after_signup",
                    person_id=stopped_after_signup_person_id,
                )

            with freeze_time("2012-01-01T03:21:36.000Z"):
                stopped_after_pay_person_id = uuid.uuid4()
                person_factory(distinct_ids=["stopped_after_pay"], team_id=self.team.pk)
                self._signup_event(
                    distinct_id="stopped_after_pay",
                    person_id=stopped_after_pay_person_id,
                )
            with freeze_time("2012-01-01T03:21:37.000Z"):
                self._pay_event(
                    distinct_id="stopped_after_pay",
                    person_id=stopped_after_pay_person_id,
                )

            with freeze_time("2012-01-01T03:21:38.000Z"):
                had_anonymous_id_person_id = uuid.uuid4()
                person_factory(
                    distinct_ids=["had_anonymous_id", "completed_movie"],
                    team_id=self.team.pk,
                )
                self._signup_event(distinct_id="had_anonymous_id", person_id=had_anonymous_id_person_id)
            with freeze_time("2012-01-01T03:21:39.000Z"):
                self._pay_event(distinct_id="completed_movie", person_id=had_anonymous_id_person_id)
            with freeze_time("2012-01-01T03:21:40.000Z"):
                self._movie_event(distinct_id="completed_movie", person_id=had_anonymous_id_person_id)

            with freeze_time("2012-01-01T03:21:41.000Z"):
                just_did_movie_person_id = uuid.uuid4()
                person_factory(distinct_ids=["just_did_movie"], team_id=self.team.pk)
                self._movie_event(distinct_id="just_did_movie", person_id=just_did_movie_person_id)

            with freeze_time("2012-01-01T03:21:42.000Z"):
                wrong_order_person_id = uuid.uuid4()
                person_factory(distinct_ids=["wrong_order"], team_id=self.team.pk)
                self._pay_event(distinct_id="wrong_order", person_id=wrong_order_person_id)
            with freeze_time("2012-01-01T03:21:43.000Z"):
                self._signup_event(distinct_id="wrong_order", person_id=wrong_order_person_id)
            with freeze_time("2012-01-01T03:21:44.000Z"):
                self._movie_event(distinct_id="wrong_order", person_id=wrong_order_person_id)

            with freeze_time("2012-01-01T03:21:45.000Z"):
                create_person_id_override_by_distinct_id("stopped_after_signup", "stopped_after_pay", self.team.pk)

            with freeze_time("2012-01-01T03:21:46.000Z"):
                result = funnel.calculate().results
                self.assertEqual(result[0]["name"], "user signed up")

                # key difference between this test and test_funnel_events.
                # we merged two people and thus the count here is 3 and not 4
                self.assertEqual(result[0]["count"], 3)

                self.assertEqual(result[1]["name"], "paid")
                self.assertEqual(result[1]["count"], 2)
                self.assertEqual(result[2]["name"], "watched movie")
                self.assertEqual(result[2]["count"], 1)

        def test_funnel_with_messed_up_order(self):
            action_play_movie = Action.objects.create(
                team=self.team,
                name="watched movie",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "tag_name": "a",
                        "href": "/movie",
                    }
                ],
            )

            funnel = self._basic_funnel(
                filters={
                    "events": [{"id": "user signed up", "type": "events", "order": 0}],
                    "actions": [{"id": action_play_movie.pk, "type": "actions", "order": 2}],
                    "funnel_window_days": 14,
                }
            )

            # events
            person_factory(distinct_ids=["stopped_after_signup"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_signup")

            person_factory(distinct_ids=["stopped_after_pay"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_pay")
            self._movie_event(distinct_id="completed_movie")

            person_factory(
                distinct_ids=["had_anonymous_id", "completed_movie"],
                team_id=self.team.pk,
            )
            self._signup_event(distinct_id="had_anonymous_id")
            self._movie_event(distinct_id="completed_movie")

            person_factory(distinct_ids=["just_did_movie"], team_id=self.team.pk)
            self._movie_event(distinct_id="just_did_movie")

            person_factory(distinct_ids=["wrong_order"], team_id=self.team.pk)
            self._movie_event(distinct_id="wrong_order")
            self._signup_event(distinct_id="wrong_order")

            result = funnel.calculate().results
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 4)

            self.assertEqual(result[1]["name"], "watched movie")
            self.assertEqual(result[1]["count"], 1)

        def test_funnel_with_any_event(self):
            funnel = self._basic_funnel(
                filters={
                    "events": [
                        {"id": None, "type": "events", "order": 0},
                        {"id": None, "type": "events", "order": 1},
                        {"id": None, "type": "events", "order": 2},
                    ],
                    "funnel_window_days": 14,
                }
            )

            # events
            person_factory(distinct_ids=["stopped_after_signup"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_signup")

            person_factory(distinct_ids=["stopped_after_pay"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_pay")
            self._movie_event(distinct_id="stopped_after_pay")

            person_factory(distinct_ids=["completed_movie"], team_id=self.team.pk)
            self._signup_event(distinct_id="completed_movie")
            self._movie_event(distinct_id="completed_movie")

            person_factory(distinct_ids=["just_did_movie"], team_id=self.team.pk)
            self._movie_event(distinct_id="just_did_movie")

            person_factory(distinct_ids=["wrong_order"], team_id=self.team.pk)
            self._movie_event(distinct_id="wrong_order")
            self._signup_event(distinct_id="wrong_order")
            self._movie_event(distinct_id="wrong_order")

            result = funnel.calculate().results
            self.assertEqual(result[0]["name"], None)
            self.assertEqual(result[0]["count"], 5)

            self.assertEqual(result[1]["name"], None)
            self.assertEqual(result[1]["count"], 3)

            self.assertEqual(result[2]["name"], None)
            self.assertEqual(result[2]["count"], 1)

        # TODO: obsolete test as new entities aren't part of the query schema?
        def test_funnel_with_new_entities_that_mess_up_order(self):
            action_play_movie = Action.objects.create(
                team=self.team,
                name="watched movie",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "tag_name": "a",
                        "href": "/movie",
                    }
                ],
            )

            funnel = self._basic_funnel(
                filters={
                    "events": [{"id": "user signed up", "type": "events", "order": 1}],
                    "actions": [{"id": action_play_movie.pk, "type": "actions", "order": 2}],
                    "new_entities": [
                        {"id": "first", "type": "new_entity", "order": 0},
                        {"id": "last", "type": "new_entity", "order": 3},
                    ],
                    "funnel_window_days": 14,
                }
            )

            # events
            person_factory(distinct_ids=["stopped_after_signup"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_signup")

            person_factory(distinct_ids=["stopped_after_pay"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_pay")
            self._movie_event(distinct_id="completed_movie")

            person_factory(
                distinct_ids=["had_anonymous_id", "completed_movie"],
                team_id=self.team.pk,
            )
            self._signup_event(distinct_id="had_anonymous_id")
            self._movie_event(distinct_id="completed_movie")

            person_factory(distinct_ids=["just_did_movie"], team_id=self.team.pk)
            self._movie_event(distinct_id="just_did_movie")

            person_factory(distinct_ids=["wrong_order"], team_id=self.team.pk)
            self._movie_event(distinct_id="wrong_order")
            self._signup_event(distinct_id="wrong_order")

            result = funnel.calculate().results
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 4)

            self.assertEqual(result[1]["name"], "watched movie")
            self.assertEqual(result[1]["count"], 1)

        def test_funnel_skipped_step(self):
            funnel = self._basic_funnel()

            person_factory(distinct_ids=["wrong_order"], team_id=self.team.pk)
            self._signup_event(distinct_id="wrong_order")
            self._movie_event(distinct_id="wrong_order")

            result = funnel.calculate().results
            self.assertEqual(result[1]["count"], 0)
            self.assertEqual(result[2]["count"], 0)

        @also_test_with_materialized_columns(["$browser"])
        def test_funnel_prop_filters(self):
            funnel = self._basic_funnel(properties={"$browser": "Safari"})

            # events
            person_factory(distinct_ids=["with_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="with_property", properties={"$browser": "Safari"})
            self._pay_event(distinct_id="with_property", properties={"$browser": "Safari"})

            # should not add a count
            person_factory(distinct_ids=["without_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="without_property")
            self._pay_event(distinct_id="without_property")

            # will add to first step
            person_factory(distinct_ids=["half_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="half_property", properties={"$browser": "Safari"})
            self._pay_event(distinct_id="half_property")

            result = funnel.calculate().results
            self.assertEqual(result[0]["count"], 2)
            self.assertEqual(result[1]["count"], 1)

        @also_test_with_materialized_columns(["$browser"])
        def test_funnel_prop_filters_per_entity(self):
            action_credit_card = Action.objects.create(
                team_id=self.team.pk,
                name="paid",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "tag_name": "button",
                        "text": "Pay $10",
                    }
                ],
            )
            action_play_movie = Action.objects.create(
                team_id=self.team.pk,
                name="watched movie",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "tag_name": "a",
                        "href": "/movie",
                    }
                ],
            )
            filters = {
                "events": [
                    {
                        "id": "user signed up",
                        "type": "events",
                        "order": 0,
                        "properties": [
                            {"key": "$browser", "value": "Safari"},
                            {
                                "key": "$browser",
                                "operator": "is_not",
                                "value": "Chrome",
                            },
                        ],
                    }
                ],
                "actions": [
                    {
                        "id": action_credit_card.pk,
                        "type": "actions",
                        "order": 1,
                        "properties": [{"key": "$browser", "value": "Safari"}],
                    },
                    {
                        "id": action_play_movie.pk,
                        "type": "actions",
                        "order": 2,
                        "properties": [{"key": "$browser", "value": "Firefox"}],
                    },
                ],
                "funnel_window_days": 14,
            }
            funnel = self._basic_funnel(filters=filters)

            # events
            person_factory(
                distinct_ids=["with_property"],
                team_id=self.team.pk,
                properties={"$browser": "Safari"},
            )
            self._signup_event(distinct_id="with_property", properties={"$browser": "Safari"})
            self._pay_event(distinct_id="with_property", properties={"$browser": "Safari"})
            self._movie_event(distinct_id="with_property")

            # should not add a count
            person_factory(distinct_ids=["without_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="without_property")
            self._pay_event(distinct_id="without_property", properties={"$browser": "Safari"})

            # will add to first step
            person_factory(distinct_ids=["half_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="half_property")
            self._pay_event(distinct_id="half_property")
            self._movie_event(distinct_id="half_property")

            result = funnel.calculate().results

            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(result[1]["count"], 1)
            self.assertEqual(result[2]["count"], 0)

        @also_test_with_materialized_columns(person_properties=["email"])
        def test_funnel_person_prop(self):
            action_credit_card = Action.objects.create(
                team_id=self.team.pk,
                name="paid",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "tag_name": "button",
                        "text": "Pay $10",
                    }
                ],
            )
            action_play_movie = Action.objects.create(
                team_id=self.team.pk,
                name="watched movie",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "tag_name": "a",
                        "href": "/movie",
                    }
                ],
            )
            filters = {
                "events": [
                    {
                        "id": "user signed up",
                        "type": "events",
                        "order": 0,
                        "properties": [
                            {
                                "key": "email",
                                "value": "hello@posthog.com",
                                "type": "person",
                            }
                        ],
                    }
                ],
                "actions": [
                    {"id": action_credit_card.pk, "type": "actions", "order": 1},
                    {"id": action_play_movie.pk, "type": "actions", "order": 2},
                ],
                "funnel_window_days": 14,
            }
            funnel = self._basic_funnel(filters=filters)

            # events
            person_factory(
                distinct_ids=["with_property"],
                team_id=self.team.pk,
                properties={"email": "hello@posthog.com"},
            )
            self._signup_event(distinct_id="with_property")
            self._pay_event(distinct_id="with_property")
            self._movie_event(distinct_id="with_property")

            result = funnel.calculate().results
            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(result[1]["count"], 1)
            self.assertEqual(result[2]["count"], 1)

        @also_test_with_materialized_columns(["test_propX"])
        def test_funnel_multiple_actions(self):
            # we had an issue on clickhouse where multiple actions with different property filters would incorrectly grab only the last
            # properties.
            # This test prevents a regression
            person_factory(distinct_ids=["person1"], team_id=self.team.pk)
            event_factory(distinct_id="person1", event="event1", team=self.team)
            event_factory(
                distinct_id="person1",
                event="event2",
                properties={"test_propX": "a"},
                team=self.team,
            )

            action1 = Action.objects.create(
                team_id=self.team.pk,
                name="event2",
                steps_json=[
                    {
                        "event": "event2",
                        "properties": [{"key": "test_propX", "value": "a"}],
                    }
                ],
            )
            action2 = Action.objects.create(
                team_id=self.team.pk,
                name="event2",
                steps_json=[
                    {
                        "event": "event2",
                        "properties": [{"key": "test_propX", "value": "c"}],
                    }
                ],
            )

            filters = {
                "events": [{"id": "event1", "order": 0}],
                "actions": [
                    {"id": action1.pk, "order": 1},
                    {"id": action2.pk, "order": 2},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
            }
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 1)
            self.assertEqual(results[1]["count"], 1)
            self.assertEqual(results[2]["count"], 0)

        @also_test_with_materialized_columns(person_properties=["email"])
        def test_funnel_filter_test_accounts(self):
            person_factory(
                distinct_ids=["person1"],
                team_id=self.team.pk,
                properties={"email": "test@posthog.com"},
            )
            person_factory(distinct_ids=["person2"], team_id=self.team.pk)
            event_factory(distinct_id="person1", event="event1", team=self.team)
            event_factory(distinct_id="person2", event="event1", team=self.team)

            filters = {
                "events": [{"id": "event1", "order": 0}, {"id": "event1", "order": 1}],
                "insight": INSIGHT_FUNNELS,
                "filter_test_accounts": True,
                "funnel_window_days": 14,
            }
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 1)

        @also_test_with_materialized_columns(person_properties=["email"])
        def test_funnel_with_entity_person_property_filters(self):
            person_factory(
                distinct_ids=["person1"],
                team_id=self.team.pk,
                properties={"email": "test@posthog.com"},
            )
            person_factory(
                distinct_ids=["person2"],
                team_id=self.team.pk,
                properties={"email": "another@example.com"},
            )
            person_factory(distinct_ids=["person3"], team_id=self.team.pk)
            event_factory(distinct_id="person1", event="event1", team=self.team)
            event_factory(distinct_id="person2", event="event1", team=self.team)
            event_factory(distinct_id="person3", event="event1", team=self.team)

            filters = {
                "events": [
                    {
                        "id": "event1",
                        "order": 0,
                        "properties": [
                            {
                                "key": "email",
                                "value": "is_set",
                                "operator": "is_set",
                                "type": "person",
                            }
                        ],
                    },
                    {"id": None, "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
            }
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 2)

        @also_test_with_materialized_columns(person_properties=["email"], verify_no_jsonextract=False)
        def test_funnel_filter_by_action_with_person_properties(self):
            person_factory(
                distinct_ids=["person1"],
                team_id=self.team.pk,
                properties={"email": "test@posthog.com"},
            )
            person_factory(
                distinct_ids=["person2"],
                team_id=self.team.pk,
                properties={"email": "another@example.com"},
            )
            person_factory(distinct_ids=["person3"], team_id=self.team.pk)
            event_factory(distinct_id="person1", event="event1", team=self.team)
            event_factory(distinct_id="person2", event="event1", team=self.team)
            event_factory(distinct_id="person3", event="event1", team=self.team)

            action = Action.objects.create(
                team_id=self.team.pk,
                name="event1",
                steps_json=[
                    {
                        "event": "event1",
                        "properties": [
                            {
                                "key": "email",
                                "value": "is_set",
                                "operator": "is_set",
                                "type": "person",
                            }
                        ],
                    }
                ],
            )

            filters = {
                "actions": [
                    {"id": action.pk, "type": "actions", "order": 0},
                    {"id": action.pk, "type": "actions", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
            }
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 2)

        def test_basic_funnel_default_funnel_days(self):
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-14",
            }

            # event
            _create_person(distinct_ids=["user_1"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="user_1",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="user_1",
                timestamp="2020-01-10T14:00:00Z",
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 1)

            self.assertEqual(results[1]["name"], "paid")
            self.assertEqual(results[1]["count"], 1)

        def test_basic_funnel_with_person_id_override_properties_joined_modifier_and_person_breakdown(self):
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-14",
                "breakdown": "$browser",
                "breakdown_type": "person",
            }

            # event
            _create_person(distinct_ids=["user_1"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="user_1",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="user_1",
                timestamp="2020-01-10T14:00:00Z",
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = (
                FunnelsQueryRunner(
                    query=query,
                    team=self.team,
                    modifiers=create_default_modifiers_for_team(
                        self.team,
                        HogQLQueryModifiers(
                            personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED
                        ),
                    ),
                )
                .calculate()
                .results
            )

            self.assertEqual(results[0][0]["name"], "user signed up")
            self.assertEqual(results[0][0]["count"], 1)

            self.assertEqual(results[0][1]["name"], "paid")
            self.assertEqual(results[0][1]["count"], 1)

        def test_basic_funnel_with_repeat_steps(self):
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "user signed up", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
            }

            # event
            person1_stopped_after_two_signups = _create_person(
                distinct_ids=["stopped_after_signup1"], team_id=self.team.pk
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_signup1",
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_signup1",
            )

            person2_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_signup2",
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 2)

            self.assertEqual(results[1]["count"], 1)

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 1),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 2),
                [person1_stopped_after_two_signups.uuid],
            )

        @also_test_with_materialized_columns(["key"])
        def test_basic_funnel_with_derivative_steps(self):
            filters = {
                "events": [
                    {
                        "id": "user signed up",
                        "type": "events",
                        "order": 0,
                        "properties": {"key": "val"},
                    },
                    {"id": "user signed up", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
            }

            # event
            person1_stopped_after_two_signups = _create_person(
                distinct_ids=["stopped_after_signup1"], team_id=self.team.pk
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_signup1",
                properties={"key": "val"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_signup1",
            )

            person2_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_signup2",
                properties={"key": "val"},
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 2)

            self.assertEqual(results[1]["count"], 1)

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 1),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 2),
                [person1_stopped_after_two_signups.uuid],
            )

        def test_basic_funnel_with_repeat_step_updated_param(self):
            people = journeys_for(
                {
                    "stopped_after_signup1": [
                        {"event": "user signed up"},
                        {"event": "user signed up"},
                    ],
                    "stopped_after_signup2": [{"event": "user signed up"}],
                },
                self.team,
            )

            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "user signed up", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_interval": 14,
                "funnel_window_interval_unit": "day",
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 2)

            self.assertEqual(results[1]["count"], 1)

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 1),
                [
                    people["stopped_after_signup1"].uuid,
                    people["stopped_after_signup2"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 2),
                [people["stopped_after_signup1"].uuid],
            )

            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "user signed up", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
                "funnel_window_interval": 2,
                "funnel_window_interval_unit": "week",
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            result2 = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            assert_funnel_results_equal(results, result2)

            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "user signed up", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
                "funnel_window_interval": 1,
                "funnel_window_interval_unit": "hour",
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            result3 = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            assert_funnel_results_equal(results, result3)

        def test_advanced_funnel_with_repeat_steps(self):
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "$pageview", "type": "events", "order": 1},
                    {"id": "$pageview", "type": "events", "order": 2},
                    {"id": "$pageview", "type": "events", "order": 3},
                    {"id": "$pageview", "type": "events", "order": 4},
                ],
                "insight": INSIGHT_FUNNELS,
            }

            people = journeys_for(
                {
                    "stopped_after_signup1": [{"event": "user signed up"}],
                    "stopped_after_pageview1": [
                        {"event": "user signed up"},
                        {"event": "$pageview"},
                    ],
                    "stopped_after_pageview2": [
                        {"event": "user signed up"},
                        {"event": "$pageview"},
                        {"event": "blaah blaa"},
                        {"event": "$pageview"},
                    ],
                    "stopped_after_pageview3": [
                        {"event": "user signed up"},
                        {"event": "$pageview"},
                        {"event": "blaah blaa"},
                        {"event": "$pageview"},
                        {"event": "$pageview"},
                        {"event": "blaah blaa"},
                    ],
                    "stopped_after_pageview4": [
                        {"event": "user signed up"},
                        {"event": "$pageview"},
                        {"event": "$pageview"},
                        {"event": "$pageview"},
                        {"event": "$pageview"},
                    ],
                },
                self.team,
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[1]["name"], "$pageview")
            self.assertEqual(results[4]["name"], "$pageview")
            self.assertEqual(results[0]["count"], 5)

            self.assertEqual(results[1]["count"], 4)

            self.assertEqual(results[2]["count"], 3)

            self.assertEqual(results[3]["count"], 2)

            self.assertEqual(results[4]["count"], 1)

            # check ordering of people in every step
            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 1),
                [
                    people["stopped_after_signup1"].uuid,
                    people["stopped_after_pageview1"].uuid,
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 2),
                [
                    people["stopped_after_pageview1"].uuid,
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 3),
                [
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 4),
                [
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 5),
                [people["stopped_after_pageview4"].uuid],
            )

        def test_advanced_funnel_with_repeat_steps_out_of_order_events(self):
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "$pageview", "type": "events", "order": 1},
                    {"id": "$pageview", "type": "events", "order": 2},
                    {"id": "$pageview", "type": "events", "order": 3},
                    {"id": "$pageview", "type": "events", "order": 4},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
            }

            # event
            person1_stopped_after_signup = _create_person(
                distinct_ids=["random", "stopped_after_signup1"], team_id=self.team.pk
            )
            _create_event(team=self.team, event="$pageview", distinct_id="random")
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_signup1",
            )

            person2_stopped_after_one_pageview = _create_person(
                distinct_ids=["stopped_after_pageview1"], team_id=self.team.pk
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_pageview1",
            )
            _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview1")

            person3_stopped_after_two_pageview = _create_person(
                distinct_ids=["stopped_after_pageview2"], team_id=self.team.pk
            )
            _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview2")
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_pageview2",
            )
            _create_event(
                team=self.team,
                event="blaah blaa",
                distinct_id="stopped_after_pageview2",
            )
            _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview2")

            person4_stopped_after_three_pageview = _create_person(
                distinct_ids=["stopped_after_pageview3"], team_id=self.team.pk
            )
            _create_event(
                team=self.team,
                event="blaah blaa",
                distinct_id="stopped_after_pageview3",
            )
            _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview3")
            _create_event(
                team=self.team,
                event="blaah blaa",
                distinct_id="stopped_after_pageview3",
            )
            _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview3")
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_pageview3",
            )
            _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview3")

            person5_stopped_after_many_pageview = _create_person(
                distinct_ids=["stopped_after_pageview4"], team_id=self.team.pk
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_pageview4",
            )
            _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")
            _create_event(
                team=self.team,
                event="blaah blaa",
                distinct_id="stopped_after_pageview4",
            )
            _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")
            _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")
            _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview4")

            _create_person(distinct_ids=["stopped_after_pageview5"], team_id=self.team.pk)
            _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview5")
            _create_event(
                team=self.team,
                event="blaah blaa",
                distinct_id="stopped_after_pageview5",
            )
            _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview5")
            _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview5")
            _create_event(team=self.team, event="$pageview", distinct_id="stopped_after_pageview5")

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[1]["name"], "$pageview")
            self.assertEqual(results[4]["name"], "$pageview")
            self.assertEqual(results[0]["count"], 5)

            self.assertEqual(results[1]["count"], 4)

            self.assertEqual(results[2]["count"], 1)

            self.assertEqual(results[3]["count"], 1)

            self.assertEqual(results[4]["count"], 1)

            # check ordering of people in every step
            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 1),
                [
                    person1_stopped_after_signup.uuid,
                    person2_stopped_after_one_pageview.uuid,
                    person3_stopped_after_two_pageview.uuid,
                    person4_stopped_after_three_pageview.uuid,
                    person5_stopped_after_many_pageview.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 2),
                [
                    person2_stopped_after_one_pageview.uuid,
                    person3_stopped_after_two_pageview.uuid,
                    person4_stopped_after_three_pageview.uuid,
                    person5_stopped_after_many_pageview.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 3),
                [person5_stopped_after_many_pageview.uuid],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 4),
                [person5_stopped_after_many_pageview.uuid],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 5),
                [person5_stopped_after_many_pageview.uuid],
            )

        @also_test_with_materialized_columns(["key"])
        def test_funnel_with_actions(self):
            sign_up_action = _create_action(
                name="sign up",
                team=self.team,
                properties=[
                    {
                        "key": "key",
                        "type": "event",
                        "value": ["val"],
                        "operator": "exact",
                    }
                ],
            )

            filters = {
                "actions": [
                    {"id": sign_up_action.id, "math": "dau", "order": 0},
                    {"id": sign_up_action.id, "math": "weekly_active", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
            }

            # event
            person1_stopped_after_two_signups = _create_person(
                distinct_ids=["stopped_after_signup1"], team_id=self.team.pk
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="stopped_after_signup1",
                properties={"key": "val"},
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="stopped_after_signup1",
                properties={"key": "val"},
            )

            person2_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="stopped_after_signup2",
                properties={"key": "val"},
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "sign up")
            self.assertEqual(results[0]["count"], 2)

            self.assertEqual(results[1]["count"], 1)

            # check ordering of people in first step
            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 1),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 2),
                [person1_stopped_after_two_signups.uuid],
            )

        def test_funnel_with_different_actions_at_same_time_count_as_converted(self):
            sign_up_action = _create_action(
                name="sign up",
                team=self.team,
                properties=[
                    {
                        "key": "key",
                        "type": "event",
                        "value": ["val"],
                        "operator": "exact",
                    }
                ],
            )

            filters = {
                "actions": [{"id": sign_up_action.id, "order": 0}],
                "events": [{"id": "$pageview", "order": 1}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-07",
            }

            with freeze_time("2020-01-03"):
                # event
                person1_stopped_after_two_signups = _create_person(
                    distinct_ids=["stopped_after_signup1"], team_id=self.team.pk
                )
                _create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id="stopped_after_signup1",
                    properties={"key": "val"},
                )
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id="stopped_after_signup1",
                    properties={"key": "val"},
                )

                person2_stopped_after_signup = _create_person(
                    distinct_ids=["stopped_after_signup2"], team_id=self.team.pk
                )
                _create_event(
                    team=self.team,
                    event="sign up",
                    distinct_id="stopped_after_signup2",
                    properties={"key": "val"},
                )

                query = cast(FunnelsQuery, filter_to_query(filters))
                results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

                self.assertEqual(results[0]["name"], "sign up")
                self.assertEqual(results[0]["count"], 2)

                self.assertEqual(results[1]["count"], 1)

                # check ordering of people in first step
                self.assertCountEqual(
                    self._get_actor_ids_at_step(filters, 1),
                    [
                        person1_stopped_after_two_signups.uuid,
                        person2_stopped_after_signup.uuid,
                    ],
                )

                self.assertCountEqual(
                    self._get_actor_ids_at_step(filters, 2),
                    [person1_stopped_after_two_signups.uuid],
                )

        def test_funnel_with_actions_and_props(self):
            sign_up_action = _create_action(
                name="sign up",
                team=self.team,
                properties=[
                    {
                        "key": "email",
                        "operator": "icontains",
                        "value": ".com",
                        "type": "person",
                    }
                ],
            )

            filters = {
                "actions": [
                    {"id": sign_up_action.id, "math": "dau", "order": 0},
                    {"id": sign_up_action.id, "math": "weekly_active", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
            }

            # event
            person1_stopped_after_two_signups = _create_person(
                distinct_ids=["stopped_after_signup1"],
                team_id=self.team.pk,
                properties={"email": "fake@test.com"},
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="stopped_after_signup1",
                properties={"key": "val"},
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="stopped_after_signup1",
                properties={"key": "val"},
            )

            person2_stopped_after_signup = _create_person(
                distinct_ids=["stopped_after_signup2"],
                team_id=self.team.pk,
                properties={"email": "fake@test.com"},
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="stopped_after_signup2",
                properties={"key": "val"},
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "sign up")
            self.assertEqual(results[0]["count"], 2)

            self.assertEqual(results[1]["count"], 1)

            # check ordering of people in first step
            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 1),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 2),
                [person1_stopped_after_two_signups.uuid],
            )

        def test_funnel_with_actions_and_props_with_zero_person_ids(self):
            # only a person-on-event test
            if not get_instance_setting("PERSON_ON_EVENTS_ENABLED"):
                return True

            sign_up_action = _create_action(
                name="sign up",
                team=self.team,
                properties=[
                    {
                        "key": "email",
                        "operator": "icontains",
                        "value": ".com",
                        "type": "person",
                    }
                ],
            )

            filters = {
                "actions": [
                    {"id": sign_up_action.id, "math": "dau", "order": 0},
                    {"id": sign_up_action.id, "math": "weekly_active", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
            }

            # event
            person1_stopped_after_two_signups = _create_person(
                distinct_ids=["stopped_after_signup1"],
                team_id=self.team.pk,
                properties={"email": "fake@test.com"},
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="stopped_after_signup1",
                properties={"key": "val"},
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="stopped_after_signup1",
                properties={"key": "val"},
            )

            person2_stopped_after_signup = _create_person(
                distinct_ids=["stopped_after_signup2"],
                team_id=self.team.pk,
                properties={"email": "fake@test.com"},
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="stopped_after_signup2",
                properties={"key": "val"},
            )

            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="zero_person_id",
                properties={"key": "val"},
                person_id="00000000-0000-0000-0000-000000000000",
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="zero_person_id",
                properties={"key": "val"},
                person_id="00000000-0000-0000-0000-000000000000",
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "sign up")
            self.assertEqual(results[0]["count"], 2)

            self.assertEqual(results[1]["count"], 1)

            # check ordering of people in first step
            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 1),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 2),
                [person1_stopped_after_two_signups.uuid],
            )

        @also_test_with_materialized_columns(["$current_url"])
        def test_funnel_with_matching_properties(self):
            filters = {
                "events": [
                    {"id": "user signed up", "order": 0},
                    {
                        "id": "$pageview",
                        "order": 1,
                        "properties": {"$current_url": "aloha.com"},
                    },
                    {
                        "id": "$pageview",
                        "order": 2,
                        "properties": {"$current_url": "aloha2.com"},
                    },  # different event to above
                    {
                        "id": "$pageview",
                        "order": 3,
                        "properties": {"$current_url": "aloha2.com"},
                    },
                    {"id": "$pageview", "order": 4},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
            }

            # event
            people = journeys_for(
                {
                    "stopped_after_signup1": [{"event": "user signed up"}],
                    "stopped_after_pageview1": [
                        {"event": "user signed up"},
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha.com"},
                        },
                    ],
                    "stopped_after_pageview2": [
                        {"event": "user signed up"},
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha.com"},
                        },
                        {
                            "event": "blaah blaa",
                            "properties": {"$current_url": "aloha.com"},
                        },
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha2.com"},
                        },
                    ],
                    "stopped_after_pageview3": [
                        {"event": "user signed up"},
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha.com"},
                        },
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha2.com"},
                        },
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha2.com"},
                        },
                        {"event": "blaah blaa"},
                    ],
                    "stopped_after_pageview4": [
                        {"event": "user signed up"},
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha.com"},
                        },
                        {"event": "blaah blaa"},
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha2.com"},
                        },
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha.com"},
                        },
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha2.com"},
                        },
                    ],
                },
                self.team,
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[1]["name"], "$pageview")
            self.assertEqual(results[4]["name"], "$pageview")
            self.assertEqual(results[0]["count"], 5)
            self.assertEqual(results[1]["count"], 4)
            self.assertEqual(results[2]["count"], 3)
            self.assertEqual(results[3]["count"], 2)
            self.assertEqual(results[4]["count"], 0)
            # check ordering of people in every step
            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 1),
                [
                    people["stopped_after_signup1"].uuid,
                    people["stopped_after_pageview1"].uuid,
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 2),
                [
                    people["stopped_after_pageview1"].uuid,
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 3),
                [
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 4),
                [
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filters, 5), [])

        def test_funnel_conversion_window(self):
            ids_to_compare = []
            for i in range(10):
                person = _create_person(distinct_ids=[f"user_{i}"], team=self.team)
                ids_to_compare.append(str(person.uuid))
                _create_event(
                    event="step one",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:00:00",
                )
                _create_event(
                    event="step two",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-02 00:00:00",
                )

            for i in range(10, 25):
                _create_person(distinct_ids=[f"user_{i}"], team=self.team)
                _create_event(
                    event="step one",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:00:00",
                )
                _create_event(
                    event="step two",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-10 00:00:00",
                )

            filters = {
                "insight": INSIGHT_FUNNELS,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-14 00:00:00",
                "funnel_window_interval": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 25)
            self.assertEqual(results[1]["count"], 10)
            self.assertEqual(results[2]["count"], 0)

            self.assertCountEqual(
                [str(id) for id in self._get_actor_ids_at_step(filters, 2)],
                ids_to_compare,
            )

        @snapshot_clickhouse_queries
        def test_funnel_conversion_window_seconds(self):
            ids_to_compare = []
            for i in range(10):
                person = _create_person(distinct_ids=[f"user_{i}"], team=self.team)
                ids_to_compare.append(str(person.uuid))
                _create_event(
                    event="step one",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:00:00",
                )
                _create_event(
                    event="step two",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:00:10",
                )

            for i in range(10, 25):
                _create_person(distinct_ids=[f"user_{i}"], team=self.team)
                _create_event(
                    event="step one",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:00:00",
                )
                _create_event(
                    event="step two",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:00:20",
                )

            filters = {
                "insight": INSIGHT_FUNNELS,
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-14 00:00:00",
                "funnel_window_interval": 15,
                "funnel_window_interval_unit": "second",
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 25)
            self.assertEqual(results[1]["count"], 10)
            self.assertEqual(results[2]["count"], 0)

            self.assertCountEqual(
                [str(id) for id in self._get_actor_ids_at_step(filters, 2)],
                ids_to_compare,
            )

        def test_funnel_exclusions_invalid_params(self):
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-14 00:00:00",
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 1,
                        "funnel_to_step": 1,
                    }
                ],
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            self.assertRaises(ValidationError, lambda: FunnelsQueryRunner(query=query, team=self.team).calculate())

            filters = {
                **filters,
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 1,
                        "funnel_to_step": 2,
                    }
                ],
            }
            query = cast(FunnelsQuery, filter_to_query(filters))
            self.assertRaises(ValidationError, lambda: FunnelsQueryRunner(query=query, team=self.team).calculate())

            filters = {
                **filters,
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 2,
                        "funnel_to_step": 1,
                    }
                ],
            }
            query = cast(FunnelsQuery, filter_to_query(filters))
            self.assertRaises(ValidationError, lambda: FunnelsQueryRunner(query=query, team=self.team).calculate())

            filters = {
                **filters,
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 2,
                    }
                ],
            }
            query = cast(FunnelsQuery, filter_to_query(filters))
            self.assertRaises(ValidationError, lambda: FunnelsQueryRunner(query=query, team=self.team).calculate())

        def test_funnel_exclusion_no_end_event(self):
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_interval": 1,
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-14 00:00:00",
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    }
                ],
            }

            # person 1
            person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person1",
                timestamp="2021-05-01 01:00:00",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="person1",
                timestamp="2021-05-01 02:00:00",
            )

            # person 2
            _create_person(distinct_ids=["person2"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person2",
                timestamp="2021-05-01 03:00:00",
            )
            _create_event(
                team=self.team,
                event="x",
                distinct_id="person2",
                timestamp="2021-05-01 03:30:00",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="person2",
                timestamp="2021-05-01 04:00:00",
            )

            # person 3
            _create_person(distinct_ids=["person3"], team_id=self.team.pk)
            # should be discarded, even if nothing happened after x, since within conversion window
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person3",
                timestamp="2021-05-01 05:00:00",
            )
            _create_event(
                team=self.team,
                event="x",
                distinct_id="person3",
                timestamp="2021-05-01 06:00:00",
            )

            # person 4 - outside conversion window
            person4 = _create_person(distinct_ids=["person4"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person4",
                timestamp="2021-05-01 07:00:00",
            )
            _create_event(
                team=self.team,
                event="x",
                distinct_id="person4",
                timestamp="2021-05-02 08:00:00",
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 2)

            self.assertEqual(results[1]["name"], "paid")
            self.assertEqual(results[1]["count"], 1)

            self.assertCountEqual(self._get_actor_ids_at_step(filters, 1), [person1.uuid, person4.uuid])
            self.assertCountEqual(self._get_actor_ids_at_step(filters, 2), [person1.uuid])

        def test_funnel_exclusion_multiple_possible_no_end_event1(self):
            journeys_for(
                {
                    "user_one": [
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                        },
                        {
                            "event": "exclusion",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 1),
                        },
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 31),
                        },
                    ],
                },
                self.team,
            )

            filters = {
                "insight": INSIGHT_FUNNELS,
                "funnel_viz_type": "steps",
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-13 23:59:59",
                "funnel_window_interval": 10,
                "funnel_window_interval_unit": "second",
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                ],
                "exclusions": [
                    {
                        "id": "exclusion",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    }
                ],
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(len(results), 2)
            self.assertEqual(1, results[0]["count"])
            self.assertEqual(0, results[1]["count"])

        def test_funnel_exclusion_multiple_possible_no_end_event2(self):
            journeys_for(
                {
                    "user_one": [
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                        },
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 31),
                        },
                        {
                            "event": "exclusion",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 32),
                        },
                    ],
                },
                self.team,
            )

            filters = {
                "insight": INSIGHT_FUNNELS,
                "funnel_viz_type": "steps",
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-13 23:59:59",
                "funnel_window_interval": 10,
                "funnel_window_interval_unit": "second",
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                ],
                "exclusions": [
                    {
                        "id": "exclusion",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    }
                ],
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(len(results), 2)
            self.assertEqual(1, results[0]["count"])
            self.assertEqual(0, results[1]["count"])

        def test_funnel_exclusion_multiple_possible_no_end_event3(self):
            journeys_for(
                {
                    "user_one": [
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                        },
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 1),
                        },
                        {
                            "event": "exclusion",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 2),
                        },
                    ],
                },
                self.team,
            )

            filters = {
                "insight": INSIGHT_FUNNELS,
                "funnel_viz_type": "steps",
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-13 23:59:59",
                "funnel_window_interval": 10,
                "funnel_window_interval_unit": "second",
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                ],
                "exclusions": [
                    {
                        "id": "exclusion",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    }
                ],
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            # There should be no events. UDF funnels returns an empty array and says "no events"
            # Old style funnels returns a count of 0
            try:
                self.assertEqual([], results)
            except AssertionError:
                self.assertEqual(len(results), 2)
                self.assertEqual(0, results[0]["count"])
                self.assertEqual(0, results[1]["count"])

        @also_test_with_materialized_columns(["key"])
        def test_funnel_exclusions_with_actions(self):
            sign_up_action = _create_action(
                name="sign up",
                team=self.team,
                properties=[
                    {
                        "key": "key",
                        "type": "event",
                        "value": ["val"],
                        "operator": "exact",
                    }
                ],
            )

            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-14 00:00:00",
                "exclusions": [
                    {
                        "id": sign_up_action.id,
                        "type": "actions",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    }
                ],
            }

            # event 1
            person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person1",
                timestamp="2021-05-01 01:00:00",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="person1",
                timestamp="2021-05-01 02:00:00",
            )

            # event 2
            _create_person(distinct_ids=["person2"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person2",
                timestamp="2021-05-01 03:00:00",
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person2",
                properties={"key": "val"},
                timestamp="2021-05-01 03:30:00",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="person2",
                timestamp="2021-05-01 04:00:00",
            )

            # event 3
            person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person3",
                timestamp="2021-05-01 05:00:00",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="person3",
                timestamp="2021-05-01 06:00:00",
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 2)

            self.assertEqual(results[1]["name"], "paid")
            self.assertEqual(results[1]["count"], 2)

            self.assertCountEqual(self._get_actor_ids_at_step(filters, 1), [person1.uuid, person3.uuid])
            self.assertCountEqual(self._get_actor_ids_at_step(filters, 2), [person1.uuid, person3.uuid])

        def test_funnel_exclusions_full_window(self):
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-14 00:00:00",
                "exclusions": [
                    {
                        "id": "x 1 name with numbers 2",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    }
                ],
            }

            # person 1
            person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person1",
                timestamp="2021-05-01 01:00:00",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="person1",
                timestamp="2021-05-01 02:00:00",
            )

            # person 2
            _create_person(distinct_ids=["person2"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person2",
                timestamp="2021-05-01 03:00:00",
            )
            _create_event(
                team=self.team,
                event="x 1 name with numbers 2",
                distinct_id="person2",
                timestamp="2021-05-01 03:30:00",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="person2",
                timestamp="2021-05-01 04:00:00",
            )

            # person 3
            person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person3",
                timestamp="2021-05-01 05:00:00",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="person3",
                timestamp="2021-05-01 06:00:00",
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 2)

            self.assertEqual(results[1]["name"], "paid")
            self.assertEqual(results[1]["count"], 2)

            self.assertCountEqual(self._get_actor_ids_at_step(filters, 1), [person1.uuid, person3.uuid])
            self.assertCountEqual(self._get_actor_ids_at_step(filters, 2), [person1.uuid, person3.uuid])

        def test_advanced_funnel_exclusions_between_steps(self):
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "$pageview", "type": "events", "order": 1},
                    {"id": "insight viewed", "type": "events", "order": 2},
                    {"id": "invite teammate", "type": "events", "order": 3},
                    {"id": "pageview2", "type": "events", "order": 4},
                ],
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-14 00:00:00",
                "insight": INSIGHT_FUNNELS,
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    }
                ],
            }

            person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
            # this dude is discarded when funnel_from_step = 1
            # this dude is discarded when funnel_from_step = 2
            # this dude is discarded when funnel_from_step = 3
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person1",
                timestamp="2021-05-01 01:00:00",
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="person1",
                timestamp="2021-05-01 02:00:00",
            )
            _create_event(
                team=self.team,
                event="x",
                distinct_id="person1",
                timestamp="2021-05-01 03:00:00",
            )
            _create_event(
                team=self.team,
                event="insight viewed",
                distinct_id="person1",
                timestamp="2021-05-01 04:00:00",
            )
            _create_event(
                team=self.team,
                event="x",
                distinct_id="person1",
                timestamp="2021-05-01 04:30:00",
            )
            _create_event(
                team=self.team,
                event="invite teammate",
                distinct_id="person1",
                timestamp="2021-05-01 05:00:00",
            )
            _create_event(
                team=self.team,
                event="x",
                distinct_id="person1",
                timestamp="2021-05-01 05:30:00",
            )
            _create_event(
                team=self.team,
                event="pageview2",
                distinct_id="person1",
                timestamp="2021-05-01 06:00:00",
            )

            person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
            # this dude is discarded when funnel_from_step = 2
            # this dude is discarded when funnel_from_step = 3
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person2",
                timestamp="2021-05-01 01:00:00",
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="person2",
                timestamp="2021-05-01 02:00:00",
            )
            _create_event(
                team=self.team,
                event="insight viewed",
                distinct_id="person2",
                timestamp="2021-05-01 04:00:00",
            )
            _create_event(
                team=self.team,
                event="x",
                distinct_id="person2",
                timestamp="2021-05-01 04:30:00",
            )
            _create_event(
                team=self.team,
                event="invite teammate",
                distinct_id="person2",
                timestamp="2021-05-01 05:00:00",
            )
            _create_event(
                team=self.team,
                event="x",
                distinct_id="person2",
                timestamp="2021-05-01 05:30:00",
            )
            _create_event(
                team=self.team,
                event="pageview2",
                distinct_id="person2",
                timestamp="2021-05-01 06:00:00",
            )

            person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
            # this dude is discarded when funnel_from_step = 0
            # this dude is discarded when funnel_from_step = 3
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person3",
                timestamp="2021-05-01 01:00:00",
            )
            _create_event(
                team=self.team,
                event="x",
                distinct_id="person3",
                timestamp="2021-05-01 01:30:00",
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="person3",
                timestamp="2021-05-01 02:00:00",
            )
            _create_event(
                team=self.team,
                event="insight viewed",
                distinct_id="person3",
                timestamp="2021-05-01 04:00:00",
            )
            _create_event(
                team=self.team,
                event="invite teammate",
                distinct_id="person3",
                timestamp="2021-05-01 05:00:00",
            )
            _create_event(
                team=self.team,
                event="x",
                distinct_id="person3",
                timestamp="2021-05-01 05:30:00",
            )
            _create_event(
                team=self.team,
                event="pageview2",
                distinct_id="person3",
                timestamp="2021-05-01 06:00:00",
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 2)

            self.assertEqual(results[4]["count"], 2)

            self.assertCountEqual(self._get_actor_ids_at_step(filters, 1), [person1.uuid, person2.uuid])

            filters = {
                **filters,
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 1,
                        "funnel_to_step": 2,
                    }
                ],
            }
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 2)

            self.assertEqual(results[4]["count"], 2)

            self.assertCountEqual(self._get_actor_ids_at_step(filters, 1), [person2.uuid, person3.uuid])

            filters = {
                **filters,
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 2,
                        "funnel_to_step": 3,
                    }
                ],
            }
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 1)

            self.assertEqual(results[4]["count"], 1)

            self.assertCountEqual(self._get_actor_ids_at_step(filters, 1), [person3.uuid])

            filters = {
                **filters,
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 3,
                        "funnel_to_step": 4,
                    }
                ],
            }
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            # There should be no events. UDF funnels returns an empty array and says "no events"
            # Old style funnels returns a count of 0
            try:
                self.assertEqual([], results)
            except AssertionError:
                self.assertEqual(results[0]["name"], "user signed up")
                self.assertEqual(results[0]["count"], 0)
                self.assertEqual(results[4]["count"], 0)

            self.assertCountEqual(self._get_actor_ids_at_step(filters, 1), [])

            #  bigger step window
            filters = {
                **filters,
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 1,
                        "funnel_to_step": 3,
                    }
                ],
            }
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 1)

            self.assertEqual(results[4]["count"], 1)

            self.assertCountEqual(self._get_actor_ids_at_step(filters, 1), [person3.uuid])

        def test_advanced_funnel_multiple_exclusions_between_steps(self):
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "$pageview", "type": "events", "order": 1},
                    {"id": "insight viewed", "type": "events", "order": 2},
                    {"id": "invite teammate", "type": "events", "order": 3},
                    {"id": "pageview2", "type": "events", "order": 4},
                ],
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-14 00:00:00",
                "insight": INSIGHT_FUNNELS,
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    },
                    {
                        "id": "y",
                        "type": "events",
                        "funnel_from_step": 2,
                        "funnel_to_step": 3,
                    },
                ],
            }

            _create_person(distinct_ids=["person1"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person1",
                timestamp="2021-05-01 01:00:00",
            )
            _create_event(
                team=self.team,
                event="x",
                distinct_id="person1",
                timestamp="2021-05-01 02:00:00",
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="person1",
                timestamp="2021-05-01 03:00:00",
            )
            _create_event(
                team=self.team,
                event="insight viewed",
                distinct_id="person1",
                timestamp="2021-05-01 04:00:00",
            )
            _create_event(
                team=self.team,
                event="y",
                distinct_id="person1",
                timestamp="2021-05-01 04:30:00",
            )
            _create_event(
                team=self.team,
                event="invite teammate",
                distinct_id="person1",
                timestamp="2021-05-01 05:00:00",
            )
            _create_event(
                team=self.team,
                event="pageview2",
                distinct_id="person1",
                timestamp="2021-05-01 06:00:00",
            )

            _create_person(distinct_ids=["person2"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person2",
                timestamp="2021-05-01 01:00:00",
            )
            _create_event(
                team=self.team,
                event="y",
                distinct_id="person2",
                timestamp="2021-05-01 01:30:00",
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="person2",
                timestamp="2021-05-01 02:00:00",
            )
            _create_event(
                team=self.team,
                event="insight viewed",
                distinct_id="person2",
                timestamp="2021-05-01 04:00:00",
            )
            _create_event(
                team=self.team,
                event="y",
                distinct_id="person2",
                timestamp="2021-05-01 04:30:00",
            )
            _create_event(
                team=self.team,
                event="invite teammate",
                distinct_id="person2",
                timestamp="2021-05-01 05:00:00",
            )
            _create_event(
                team=self.team,
                event="x",
                distinct_id="person2",
                timestamp="2021-05-01 05:30:00",
            )
            _create_event(
                team=self.team,
                event="pageview2",
                distinct_id="person2",
                timestamp="2021-05-01 06:00:00",
            )

            _create_person(distinct_ids=["person3"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person3",
                timestamp="2021-05-01 01:00:00",
            )
            _create_event(
                team=self.team,
                event="x",
                distinct_id="person3",
                timestamp="2021-05-01 01:30:00",
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="person3",
                timestamp="2021-05-01 02:00:00",
            )
            _create_event(
                team=self.team,
                event="insight viewed",
                distinct_id="person3",
                timestamp="2021-05-01 04:00:00",
            )
            _create_event(
                team=self.team,
                event="invite teammate",
                distinct_id="person3",
                timestamp="2021-05-01 05:00:00",
            )
            _create_event(
                team=self.team,
                event="x",
                distinct_id="person3",
                timestamp="2021-05-01 05:30:00",
            )
            _create_event(
                team=self.team,
                event="pageview2",
                distinct_id="person3",
                timestamp="2021-05-01 06:00:00",
            )

            person4 = _create_person(distinct_ids=["person4"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person4",
                timestamp="2021-05-01 01:00:00",
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="person4",
                timestamp="2021-05-01 02:00:00",
            )
            _create_event(
                team=self.team,
                event="insight viewed",
                distinct_id="person4",
                timestamp="2021-05-01 04:00:00",
            )
            _create_event(
                team=self.team,
                event="invite teammate",
                distinct_id="person4",
                timestamp="2021-05-01 05:00:00",
            )
            _create_event(
                team=self.team,
                event="pageview2",
                distinct_id="person4",
                timestamp="2021-05-01 06:00:00",
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 1)

            self.assertEqual(results[4]["count"], 1)

            self.assertCountEqual(self._get_actor_ids_at_step(filters, 1), [person4.uuid])

            filters = {
                **filters,
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    },
                    {
                        "id": "y",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    },
                ],
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 1)

            self.assertEqual(results[4]["count"], 1)

            self.assertCountEqual(self._get_actor_ids_at_step(filters, 1), [person4.uuid])

            filters = {
                **filters,
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    },
                    {
                        "id": "y",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    },
                ],
            }
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 1)

            self.assertEqual(results[4]["count"], 1)

            self.assertCountEqual(self._get_actor_ids_at_step(filters, 1), [person4.uuid])

            filters = {
                **filters,
                "exclusions": [
                    {
                        "id": "x",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 4,
                    },
                    {
                        "id": "y",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 4,
                    },
                ],
            }
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 1)

            self.assertEqual(results[4]["count"], 1)

            self.assertCountEqual(self._get_actor_ids_at_step(filters, 1), [person4.uuid])

        @also_test_with_materialized_columns(["test_prop"])
        def test_funnel_with_denormalised_properties(self):
            filters = {
                "events": [
                    {
                        "id": "user signed up",
                        "type": "events",
                        "order": 0,
                        "properties": [{"key": "test_prop", "value": "hi"}],
                    },
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "properties": [{"key": "test_prop", "value": "hi"}],
                "date_to": "2020-01-14",
            }

            # event
            _create_person(distinct_ids=["user_1"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="user_1",
                timestamp="2020-01-02T14:00:00Z",
                properties={"test_prop": "hi"},
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="user_1",
                timestamp="2020-01-10T14:00:00Z",
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 1)

        def test_same_event_same_timestamp(self):
            _create_person(distinct_ids=["test"], team_id=self.team.pk)
            with freeze_time("2024-01-10T12:01:00"):
                for _ in range(20):
                    _create_event(team=self.team, event="step one", distinct_id="test")
            with freeze_time("2024-01-11T12:01:00"):
                _create_event(team=self.team, event="step two", distinct_id="test")
            filters = {
                "insight": INSIGHT_FUNNELS,
                "funnel_viz_type": "steps",
                "date_from": "2024-01-10 00:00:00",
                "date_to": "2024-01-12 00:00:00",
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                ],
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
            self.assertEqual(results[-1]["count"], 1)

        def test_funnel_with_elements_chain(self):
            person1 = _create_person(distinct_ids=["test"], team_id=self.team.pk)
            _create_event(team=self.team, event="user signed up", distinct_id="test")
            _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id="test",
                properties={"$current_url": "http://example.com/something_else"},
                elements=[Element(tag_name="img"), Element(tag_name="svg")],
            )

            person2 = _create_person(distinct_ids=["test2"], team_id=self.team.pk)
            _create_event(team=self.team, event="user signed up", distinct_id="test2")

            for tag_name in ["img", "svg"]:
                filters = {
                    "events": [
                        {"id": "user signed up", "type": "events", "order": 0},
                        {
                            "id": "$autocapture",
                            "name": "$autocapture",
                            "order": 1,
                            "properties": [
                                {
                                    "key": "tag_name",
                                    "value": [tag_name],
                                    "operator": "exact",
                                    "type": "element",
                                }
                            ],
                            "type": "events",
                        },
                    ],
                    "insight": INSIGHT_FUNNELS,
                }

                query = cast(FunnelsQuery, filter_to_query(filters))
                results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

                self.assertEqual(len(results), 2)
                self.assertEqual(results[0]["name"], "user signed up")
                self.assertEqual(results[0]["count"], 2)

                self.assertEqual(results[1]["name"], "$autocapture")
                self.assertEqual(results[1]["count"], 1)

                self.assertCountEqual(self._get_actor_ids_at_step(filters, 1), [person1.uuid, person2.uuid])
                self.assertCountEqual(self._get_actor_ids_at_step(filters, 2), [person1.uuid])

        # TODO: fix this test
        # @snapshot_clickhouse_queries
        # def test_funnel_with_cohorts_step_filter(self):
        #     _create_person(
        #         distinct_ids=["user_1"],
        #         team_id=self.team.pk,
        #         properties={"email": "n@test.com"},
        #     )
        #     _create_event(
        #         team=self.team,
        #         event="user signed up",
        #         distinct_id="user_1",
        #         timestamp="2020-01-02T14:00:00Z",
        #     )
        #     _create_event(
        #         team=self.team,
        #         event="paid",
        #         distinct_id="user_1",
        #         timestamp="2020-01-10T14:00:00Z",
        #     )

        #     _create_person(distinct_ids=["user_2"], team_id=self.team.pk)
        #     _create_event(
        #         team=self.team,
        #         event="user signed up",
        #         distinct_id="user_2",
        #         timestamp="2020-01-02T14:00:00Z",
        #     )
        #     _create_event(
        #         team=self.team,
        #         event="paid",
        #         distinct_id="user_2",
        #         timestamp="2020-01-10T14:00:00Z",
        #     )

        #     cohort = Cohort.objects.create(
        #         team=self.team,
        #         groups=[
        #             {
        #                 "properties": [
        #                     {
        #                         "key": "email",
        #                         "operator": "icontains",
        #                         "value": ".com",
        #                         "type": "person",
        #                     }
        #                 ]
        #             }
        #         ],
        #     )

        #     filters = {
        #         "events": [
        #             {
        #                 "id": "user signed up",
        #                 "type": "events",
        #                 "order": 0,
        #                 "properties": [{"type": "cohort", "key": "id", "value": cohort.pk}],
        #             },
        #             {"id": "paid", "type": "events", "order": 1},
        #         ],
        #         "insight": INSIGHT_FUNNELS,
        #         "date_from": "2020-01-01",
        #         "date_to": "2020-01-14",
        #     }

        #     query = cast(FunnelsQuery, filter_to_query(filters))
        #     results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        #     self.assertEqual(results[0]["name"], "user signed up")
        #     self.assertEqual(results[0]["count"], 1)

        #     self.assertEqual(results[1]["name"], "paid")
        #     self.assertEqual(results[1]["count"], 1)

        @snapshot_clickhouse_queries
        def test_funnel_with_precalculated_cohort_step_filter(self):
            _create_person(
                distinct_ids=["user_1"],
                team_id=self.team.pk,
                properties={"email": "n@test.com"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="user_1",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="user_1",
                timestamp="2020-01-10T14:00:00Z",
            )

            _create_person(distinct_ids=["user_2"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="user_2",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="user_2",
                timestamp="2020-01-10T14:00:00Z",
            )

            cohort = Cohort.objects.create(
                team=self.team,
                groups=[
                    {
                        "properties": [
                            {
                                "key": "email",
                                "operator": "icontains",
                                "value": ".com",
                                "type": "person",
                            }
                        ]
                    }
                ],
            )

            filters = {
                "events": [
                    {
                        "id": "user signed up",
                        "type": "events",
                        "order": 0,
                        "properties": [
                            {
                                "type": "precalculated-cohort",
                                "key": "id",
                                "value": cohort.pk,
                            }
                        ],
                    },
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-14",
            }

            # converts to precalculated-cohort due to simplify filters
            cohort.calculate_people_ch(pending_version=0)

            with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
                query = cast(FunnelsQuery, filter_to_query(filters))
                results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
                self.assertEqual(results[0]["name"], "user signed up")
                self.assertEqual(results[0]["count"], 1)

                self.assertEqual(results[1]["name"], "paid")
                self.assertEqual(results[1]["count"], 1)

        @snapshot_clickhouse_queries
        def test_funnel_with_static_cohort_step_filter(self):
            _create_person(
                distinct_ids=["user_1"],
                team_id=self.team.pk,
                properties={"email": "n@test.com"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="user_1",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="user_1",
                timestamp="2020-01-10T14:00:00Z",
            )

            _create_person(distinct_ids=["user_2"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="user_2",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id="user_2",
                timestamp="2020-01-10T14:00:00Z",
            )

            cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
            cohort.insert_users_by_list(["user_2", "rando"])

            filters = {
                "events": [
                    {
                        "id": "user signed up",
                        "type": "events",
                        "order": 0,
                        "properties": [{"type": "static-cohort", "key": "id", "value": cohort.pk}],
                    },
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-14",
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 1)

            self.assertEqual(results[1]["name"], "paid")
            self.assertEqual(results[1]["count"], 1)

        @snapshot_clickhouse_queries
        @also_test_with_materialized_columns(["$current_url"], person_properties=["email", "age"])
        def test_funnel_with_property_groups(self):
            filters = {
                "date_from": "2020-01-01 00:00:00",
                "date_to": "2020-07-01 00:00:00",
                "events": [
                    {"id": "user signed up", "order": 0},
                    {
                        "id": "$pageview",
                        "order": 1,
                        "properties": {"$current_url": "aloha.com"},
                    },
                    {
                        "id": "$pageview",
                        "order": 2,
                        "properties": {"$current_url": "aloha2.com"},
                    },  # different event to above
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "operator": "icontains",
                                    "value": ".com",
                                    "type": "person",
                                },
                                {
                                    "key": "age",
                                    "operator": "exact",
                                    "value": "20",
                                    "type": "person",
                                },
                            ],
                        },
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "email",
                                    "operator": "icontains",
                                    "value": ".org",
                                    "type": "person",
                                },
                                {
                                    "key": "age",
                                    "operator": "exact",
                                    "value": "28",
                                    "type": "person",
                                },
                            ],
                        },
                    ],
                },
            }

            people = {}
            people["stopped_after_signup1"] = _create_person(
                distinct_ids=["stopped_after_signup1"],
                team_id=self.team.pk,
                properties={"email": "test@b.com", "age": "18"},
            )
            people["stopped_after_pageview1"] = _create_person(
                distinct_ids=["stopped_after_pageview1"],
                team_id=self.team.pk,
                properties={"email": "test@b.org", "age": "28"},
            )
            people["stopped_after_pageview2"] = _create_person(
                distinct_ids=["stopped_after_pageview2"],
                team_id=self.team.pk,
                properties={"email": "test2@b.com", "age": "28"},
            )
            people["stopped_after_pageview3"] = _create_person(
                distinct_ids=["stopped_after_pageview3"],
                team_id=self.team.pk,
                properties={"email": "test3@b.com", "age": "28"},
            )
            people["stopped_after_pageview4"] = _create_person(
                distinct_ids=["stopped_after_pageview4"],
                team_id=self.team.pk,
                properties={"email": "test4@b.org", "age": "18"},
            )

            # event
            journeys_for(
                {
                    "stopped_after_signup1": [
                        {
                            "event": "user signed up",
                            "timestamp": datetime(2020, 5, 1, 0),
                        }
                    ],
                    "stopped_after_pageview1": [
                        {
                            "event": "user signed up",
                            "timestamp": datetime(2020, 5, 1, 0),
                        }
                    ],
                    "stopped_after_pageview2": [
                        {
                            "event": "user signed up",
                            "timestamp": datetime(2020, 5, 1, 0),
                        },
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha.com"},
                            "timestamp": datetime(2020, 5, 2, 0),
                        },
                    ],
                    "stopped_after_pageview3": [
                        {
                            "event": "user signed up",
                            "timestamp": datetime(2020, 5, 1, 0),
                        },
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha.com"},
                            "timestamp": datetime(2020, 5, 2, 0),
                        },
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha2.com"},
                            "timestamp": datetime(2020, 5, 3, 0),
                        },
                    ],
                    "stopped_after_pageview4": [
                        # {"event": "user signed up"}, # no signup, so not in funnel
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha.com"},
                            "timestamp": datetime(2020, 5, 2, 0),
                        },
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha2.com"},
                            "timestamp": datetime(2020, 5, 3, 0),
                        },
                        {
                            "event": "$pageview",
                            "properties": {"$current_url": "aloha2.com"},
                            "timestamp": datetime(2020, 5, 4, 0),
                        },
                    ],
                },
                self.team,
                create_people=False,
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[1]["name"], "$pageview")
            self.assertEqual(results[2]["name"], "$pageview")
            self.assertEqual(results[0]["count"], 3)
            self.assertEqual(results[1]["count"], 2)
            self.assertEqual(results[2]["count"], 1)
            # check ordering of people in every step
            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 1),
                [
                    people["stopped_after_pageview1"].uuid,
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 2),
                [
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filters, 3),
                [people["stopped_after_pageview3"].uuid],
            )

        @snapshot_clickhouse_queries
        def test_timezones(self):
            self.team.timezone = "US/Pacific"
            self.team.save()

            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-14",
            }

            # event
            _create_person(distinct_ids=["user_1"], team_id=self.team.pk)
            # this event shouldn't appear as in US/Pacific this would be the previous day
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="user_1",
                timestamp="2020-01-01T01:00:00Z",
            )

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
            # There should be no events. UDF funnels returns an empty array and says "no events"
            # Old style funnels returns a count of 0
            try:
                self.assertEqual([], results)
            except AssertionError:
                self.assertEqual(results[0]["name"], "user signed up")
                self.assertEqual(results[0]["count"], 0)

        def test_funnel_with_sampling(self):
            action_play_movie = Action.objects.create(
                team=self.team,
                name="watched movie",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "tag_name": "a",
                        "href": "/movie",
                    }
                ],
            )

            funnel = self._basic_funnel(
                filters={
                    "events": [{"id": "user signed up", "type": "events", "order": 0}],
                    "actions": [{"id": action_play_movie.pk, "type": "actions", "order": 2}],
                    "funnel_window_days": 14,
                    "sampling_factor": 1,
                }
            )

            # events
            person_factory(distinct_ids=["stopped_after_signup"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_signup")

            person_factory(distinct_ids=["stopped_after_pay"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_pay")
            self._movie_event(distinct_id="completed_movie")

            person_factory(
                distinct_ids=["had_anonymous_id", "completed_movie"],
                team_id=self.team.pk,
            )
            self._signup_event(distinct_id="had_anonymous_id")
            self._movie_event(distinct_id="completed_movie")

            person_factory(distinct_ids=["just_did_movie"], team_id=self.team.pk)
            self._movie_event(distinct_id="just_did_movie")

            person_factory(distinct_ids=["wrong_order"], team_id=self.team.pk)
            self._movie_event(distinct_id="wrong_order")
            self._signup_event(distinct_id="wrong_order")

            results = funnel.calculate().results
            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 4)

            self.assertEqual(results[1]["name"], "watched movie")
            self.assertEqual(results[1]["count"], 1)

        def test_hogql_aggregation(self):
            # first person
            person_factory(
                distinct_ids=["user"],
                team_id=self.team.pk,
                properties={"email": "lembitu@posthog.com", "common_prop": "yes"},
            )
            self._signup_event(distinct_id="user", properties={"$session_id": "1"})
            self._add_to_cart_event(distinct_id="user", properties={"$session_id": "1"})
            self._checkout_event(distinct_id="user", properties={"$session_id": "1"})

            self._signup_event(distinct_id="user", properties={"$session_id": "2"})
            self._add_to_cart_event(distinct_id="user", properties={"$session_id": "2"})

            # second person
            person_factory(
                distinct_ids=["second"],
                team_id=self.team.pk,
                properties={"email": "toomas@posthog.com", "common_prop": "yes"},
            )
            self._signup_event(distinct_id="second", properties={"$session_id": "3"})

            basic_filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "added to cart", "type": "events", "order": 0},
                    {"id": "checked out", "type": "events", "order": 0},
                ],
                "funnel_window_days": 14,
            }

            # without hogql aggregation
            results = self._basic_funnel(filters=basic_filters).calculate().results
            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 2)
            self.assertEqual(results[1]["count"], 1)
            self.assertEqual(results[2]["count"], 1)

            # properties.$session_id
            results = (
                self._basic_funnel(
                    filters={
                        **basic_filters,
                        "funnel_aggregate_by_hogql": "properties.$session_id",
                    }
                )
                .calculate()
                .results
            )
            self.assertEqual(results[0]["count"], 3)
            self.assertEqual(results[1]["count"], 2)
            self.assertEqual(results[2]["count"], 1)

            # distinct_id
            results = (
                self._basic_funnel(filters={**basic_filters, "funnel_aggregate_by_hogql": "distinct_id"})
                .calculate()
                .results
            )
            self.assertEqual(results[0]["count"], 2)
            self.assertEqual(results[1]["count"], 1)
            self.assertEqual(results[2]["count"], 1)

            # person_id
            results = (
                self._basic_funnel(filters={**basic_filters, "funnel_aggregate_by_hogql": "person_id"})
                .calculate()
                .results
            )
            self.assertEqual(results[0]["count"], 2)
            self.assertEqual(results[1]["count"], 1)
            self.assertEqual(results[2]["count"], 1)

            result = (
                self._basic_funnel(
                    filters={**basic_filters, "funnel_aggregate_by_hogql": "person.properties.common_prop"}
                )
                .calculate()
                .results
            )
            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(result[1]["count"], 1)
            self.assertEqual(result[2]["count"], 1)

        def test_funnel_all_events_with_properties(self):
            person_factory(distinct_ids=["user"], team_id=self.team.pk)
            self._signup_event(distinct_id="user")
            self._add_to_cart_event(distinct_id="user", properties={"is_saved": True})
            PropertyDefinition.objects.get_or_create(
                team=self.team,
                type=PropertyDefinition.Type.EVENT,
                name="is_saved",
                defaults={"property_type": "Boolean"},
            )

            filters = {
                "events": [
                    {
                        "type": "events",
                        "id": "user signed up",
                        "order": 0,
                        "name": "user signed up",
                        "math": "total",
                    },
                    {
                        "type": "events",
                        "id": None,
                        "order": 1,
                        "name": "All events",
                        "math": "total",
                        "properties": [
                            {
                                "key": "is_saved",
                                "value": ["true"],
                                "operator": "exact",
                                "type": "event",
                            }
                        ],
                    },
                ],
                "funnel_window_days": 14,
            }

            results = self._basic_funnel(filters=filters).calculate().results

            self.assertEqual(results[0]["count"], 1)
            self.assertEqual(results[1]["count"], 1)

        def test_funnel_all_events_via_action(self):
            person_factory(distinct_ids=["user"], team_id=self.team.pk)
            self._signup_event(distinct_id="user")
            self._add_to_cart_event(distinct_id="user", properties={"is_saved": True})

            action_checkout_all = Action.objects.create(
                team=self.team,
                name="user signed up",
                steps_json=[
                    {"event": "checked out"},  # not performed
                    {"event": None},  # matches all
                ],
            )

            filters = {
                "events": [{"id": "user signed up", "type": "events", "order": 0}],
                "actions": [{"id": action_checkout_all.pk, "type": "actions", "order": 1}],
                "funnel_window_days": 14,
            }

            result = self._basic_funnel(filters=filters).calculate().results

            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(result[1]["count"], 1)

        def test_funnel_aggregation_with_groups_with_cohort_filtering(self):
            create_group_type_mapping_without_created_at(
                team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
            )
            create_group_type_mapping_without_created_at(
                team=self.team, project_id=self.team.project_id, group_type="company", group_type_index=1
            )

            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key="org:5",
                properties={"industry": "finance"},
            )
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key="org:6",
                properties={"industry": "technology"},
            )

            create_group(
                team_id=self.team.pk,
                group_type_index=1,
                group_key="company:1",
                properties={},
            )
            create_group(
                team_id=self.team.pk,
                group_type_index=1,
                group_key="company:2",
                properties={},
            )

            _create_person(
                distinct_ids=[f"user_1"],
                team=self.team,
                properties={"email": "fake@test.com"},
            )
            _create_person(
                distinct_ids=[f"user_2"],
                team=self.team,
                properties={"email": "fake@test.com"},
            )
            _create_person(
                distinct_ids=[f"user_3"],
                team=self.team,
                properties={"email": "fake_2@test.com"},
            )

            Action.objects.create(team=self.team, name="action1", steps_json=[{"event": "$pageview"}])

            cohort = Cohort.objects.create(
                team=self.team,
                groups=[
                    {
                        "properties": [
                            {
                                "key": "email",
                                "operator": "icontains",
                                "value": "fake@test.com",
                                "type": "person",
                            }
                        ]
                    }
                ],
            )

            events_by_person = {
                "user_1": [
                    {
                        "event": "$pageview",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$group_0": "org:5"},
                    },
                    {
                        "event": "user signed up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$group_0": "org:5"},
                    },
                    {
                        "event": "user signed up",  # same person, different group, so should count as different step 1 in funnel
                        "timestamp": datetime(2020, 1, 10, 14),
                        "properties": {"$group_0": "org:6"},
                    },
                ],
                "user_2": [
                    {  # different person, same group, so should count as step two in funnel
                        "event": "paid",
                        "timestamp": datetime(2020, 1, 3, 14),
                        "properties": {"$group_0": "org:5"},
                    }
                ],
                "user_3": [
                    {
                        "event": "user signed up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$group_0": "org:7"},
                    },
                    {  # person not in cohort so should be filtered out
                        "event": "paid",
                        "timestamp": datetime(2020, 1, 3, 14),
                        "properties": {"$group_0": "org:7"},
                    },
                ],
            }
            journeys_for(events_by_person, self.team)
            cohort.calculate_people_ch(pending_version=0)

            filters = {
                "events": [
                    {
                        "id": "user signed up",
                        "type": "events",
                        "order": 0,
                        "properties": [
                            {
                                "type": "precalculated-cohort",
                                "key": "id",
                                "value": cohort.pk,
                            }
                        ],
                    },
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-14",
                "aggregation_group_type_index": 0,
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 2)

            self.assertEqual(results[1]["name"], "paid")
            self.assertEqual(results[1]["count"], 1)

        def test_funnel_window_ignores_dst_transition(self):
            _create_person(
                distinct_ids=[f"user_1"],
                team=self.team,
            )

            events_by_person = {
                "user_1": [
                    {
                        "event": "$pageview",
                        "timestamp": datetime(2024, 3, 1, 15, 10),  # 1st March 15:10
                    },
                    {
                        "event": "user signed up",
                        "timestamp": datetime(
                            2024, 3, 15, 14, 27
                        ),  # 15th March 14:27 (within 14 day conversion window that ends at 15:10)
                    },
                ],
            }
            journeys_for(events_by_person, self.team)

            filters = {
                "events": [
                    {"id": "$pageview", "type": "events", "order": 0},
                    {"id": "user signed up", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2024-02-17",
                "date_to": "2024-03-18",
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[1]["name"], "user signed up")
            self.assertEqual(results[1]["count"], 1)
            self.assertEqual(results[1]["average_conversion_time"], 1_207_020)
            self.assertEqual(results[1]["median_conversion_time"], 1_207_020)

            # there is a PST -> PDT transition on 10th of March
            self.team.timezone = "US/Pacific"
            self.team.save()

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            # we still should have the user here, as the conversion window should not be affected by DST
            self.assertEqual(results[1]["name"], "user signed up")
            self.assertEqual(results[1]["count"], 1)
            self.assertEqual(results[1]["average_conversion_time"], 1_207_020)
            self.assertEqual(results[1]["median_conversion_time"], 1_207_020)

        def test_parses_breakdowns_correctly(self):
            _create_person(
                distinct_ids=[f"user_1"],
                team=self.team,
            )

            events_by_person = {
                "user_1": [
                    {
                        "event": "$pageview",
                        "timestamp": datetime(2024, 3, 22, 13, 46),
                        "properties": {"utm_medium": "test''123"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": datetime(2024, 3, 22, 13, 47),
                        "properties": {"utm_medium": "test''123"},
                    },
                ],
            }
            journeys_for(events_by_person, self.team)

            query = FunnelsQuery(
                series=[EventsNode(event="$pageview"), EventsNode(event="$pageview")],
                dateRange=DateRange(
                    date_from="2024-03-22",
                    date_to="2024-03-22",
                ),
                breakdownFilter=BreakdownFilter(breakdown="utm_medium"),
            )
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0][1]["breakdown_value"], ["test'123"])
            self.assertEqual(results[0][1]["count"], 1)

        def test_funnel_query_with_event_metadata_breakdown(self):
            _create_person(
                distinct_ids=[f"user_1"],
                team=self.team,
            )
            _create_person(
                distinct_ids=[f"user_2"],
                team=self.team,
            )

            events_by_person = {
                "user_1": [
                    {
                        "event": "$pageview",
                        "timestamp": datetime(2024, 3, 22, 13, 46),
                        "properties": {"utm_medium": "test''123"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": datetime(2024, 3, 22, 13, 47),
                        "properties": {"utm_medium": "test''123"},
                    },
                ],
                "user_2": [
                    {
                        "event": "$pageview",
                        "timestamp": datetime(2024, 3, 22, 13, 48),
                        "properties": {"utm_medium": "test''123"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": datetime(2024, 3, 22, 13, 49),
                        "properties": {"utm_medium": "test''123"},
                    },
                ],
            }
            journeys_for(events_by_person, self.team)

            query = FunnelsQuery(
                series=[EventsNode(event="$pageview"), EventsNode(event="$pageview")],
                dateRange=DateRange(
                    date_from="2024-03-22",
                    date_to="2024-03-22",
                ),
                breakdownFilter=BreakdownFilter(breakdown="distinct_id", breakdown_type=BreakdownType.EVENT_METADATA),
            )
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0][1]["breakdown_value"], ["user_1"])
            self.assertEqual(results[0][1]["count"], 1)
            self.assertEqual(results[1][1]["breakdown_value"], ["user_2"])
            self.assertEqual(results[1][1]["count"], 1)

        def test_funnel_parses_event_names_correctly(self):
            _create_person(
                distinct_ids=[f"user_1"],
                team=self.team,
            )

            events_by_person = {
                "user_1": [
                    {
                        "event": "test''1",
                        "timestamp": datetime(2024, 3, 22, 13, 46),
                    },
                    {
                        "event": "test''2",
                        "timestamp": datetime(2024, 3, 22, 13, 47),
                    },
                ],
            }
            journeys_for(events_by_person, self.team)

            query = FunnelsQuery(
                series=[EventsNode(event="test'1"), EventsNode()],
                dateRange=DateRange(
                    date_from="2024-03-22",
                    date_to="2024-03-22",
                ),
            )
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 1)

        def test_time_to_convert_funnel_ignores_breakdown(self):
            _create_person(distinct_ids=[f"user_1"], team=self.team, properties={"userRole": "admin"})
            _create_person(distinct_ids=[f"user_2"], team=self.team, properties={"userRole": "user"})
            _create_person(distinct_ids=[f"user_3"], team=self.team, properties={"userRole": "user"})

            events_by_person = {
                "user_1": [
                    {
                        "event": "a",
                        "timestamp": datetime(2024, 3, 22, 13, 10),
                    },
                    {
                        "event": "b",
                        "timestamp": datetime(2024, 3, 22, 13, 11),
                    },
                ],
                "user_2": [
                    {
                        "event": "a",
                        "timestamp": datetime(2024, 3, 22, 13, 1),
                    },
                    {
                        "event": "a",
                        "timestamp": datetime(2024, 3, 22, 13, 35),
                    },
                    {
                        "event": "b",
                        "timestamp": datetime(2024, 3, 22, 13, 41),
                    },
                ],
                "user_3": [
                    {
                        "event": "a",
                        "timestamp": datetime(2024, 3, 22, 13, 1),
                    },
                    {
                        "event": "a",
                        "timestamp": datetime(2024, 3, 22, 13, 35),
                    },
                    {
                        "event": "a",
                        "timestamp": datetime(2024, 3, 22, 13, 41),
                    },
                ],
            }
            journeys_for(events_by_person, self.team)

            query = FunnelsQuery(
                series=[EventsNode(event="a"), EventsNode(event="b")],
                dateRange=DateRange(
                    date_from="2024-03-22",
                    date_to="2024-03-22",
                ),
                breakdownFilter=BreakdownFilter(breakdown="userRoles", breakdown_type=BreakdownType.PERSON),
                funnelsFilter=FunnelsFilter(
                    funnelVizType=FunnelVizType.TIME_TO_CONVERT,
                    funnelWindowInterval=10,
                    funnelWindowIntervalUnit=FunnelConversionWindowTimeUnit.MINUTE,
                ),
            )
            result = FunnelsQueryRunner(query=query, team=self.team).calculate().results
            assert result.average_conversion_time == 210
            assert result.bins == [[60, 1], [210, 0], [360, 1]]

        def test_first_time_for_user_funnel_basic(self):
            _create_person(
                distinct_ids=[f"user_1"],
                team=self.team,
            )

            events_by_person = {
                "user_1": [
                    {
                        "event": "$pageview",
                        "timestamp": datetime(2024, 3, 22, 13, 46),
                    },
                    {
                        "event": "$pageview",
                        "timestamp": datetime(2024, 3, 22, 13, 47),
                    },
                ],
            }
            journeys_for(events_by_person, self.team)

            query = FunnelsQuery(
                series=[
                    EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER),
                    EventsNode(event="$pageview"),
                ],
                dateRange=DateRange(
                    date_from="2024-03-22",
                    date_to="2024-03-22",
                ),
            )
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 1)
            self.assertEqual(results[1]["count"], 1)

            query = FunnelsQuery(
                series=[
                    EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER),
                    EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER),
                ],
                dateRange=DateRange(
                    date_from="2024-03-22",
                    date_to="2024-03-22",
                ),
            )
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 1)
            self.assertEqual(results[1]["count"], 0)

        def test_first_time_for_user_funnel_with_actions(self):
            action_credit_card = Action.objects.create(
                team=self.team,
                name="paid",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "tag_name": "button",
                        "text": "Pay $10",
                    }
                ],
            )
            action_play_movie = Action.objects.create(
                team=self.team,
                name="watched movie",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "tag_name": "a",
                        "href": "/movie",
                    }
                ],
            )

            # events
            person_factory(distinct_ids=["stopped_after_signup"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_signup")

            person_factory(distinct_ids=["stopped_after_pay"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_pay")
            self._pay_event(distinct_id="stopped_after_pay")

            person_factory(
                distinct_ids=["had_anonymous_id", "completed_movie"],
                team_id=self.team.pk,
            )
            self._signup_event(distinct_id="had_anonymous_id")
            self._pay_event(distinct_id="completed_movie")
            self._movie_event(distinct_id="completed_movie")

            person_factory(distinct_ids=["just_did_movie"], team_id=self.team.pk)
            self._movie_event(distinct_id="just_did_movie")

            person_factory(distinct_ids=["wrong_order"], team_id=self.team.pk)
            self._pay_event(distinct_id="wrong_order")
            self._signup_event(distinct_id="wrong_order")
            self._movie_event(distinct_id="wrong_order")

            # somewhere in the past
            self._movie_event(distinct_id="completed_movie", timestamp="2020-01-01")

            query = FunnelsQuery(
                series=[
                    EventsNode(event="user signed up"),
                    ActionsNode(id=action_credit_card.pk),
                    ActionsNode(id=action_play_movie.pk, math=BaseMathType.FIRST_TIME_FOR_USER),
                ],
                dateRange=DateRange(
                    date_from="-14d",
                ),
            )
            result = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 4)

            self.assertEqual(result[1]["name"], "paid")
            self.assertEqual(result[1]["count"], 2)
            self.assertEqual(result[2]["name"], "watched movie")
            self.assertEqual(result[2]["count"], 0)

        def test_multiple_events_same_timestamp_exclusions(self):
            _create_person(distinct_ids=["test"], team_id=self.team.pk)
            with freeze_time("2024-01-10T12:00:00"):
                _create_event(team=self.team, event="step zero", distinct_id="test")
            with freeze_time("2024-01-10T12:01:00"):
                for _ in range(30):
                    _create_event(team=self.team, event="step one", distinct_id="test")
                _create_event(team=self.team, event="exclusion", distinct_id="test")
                _create_event(team=self.team, event="step two", distinct_id="test")
            with freeze_time("2024-01-10T12:02:00"):
                _create_event(team=self.team, event="step three", distinct_id="test")
            filters = {
                "insight": INSIGHT_FUNNELS,
                "funnel_viz_type": "steps",
                "date_from": "2024-01-10 00:00:00",
                "date_to": "2024-01-12 00:00:00",
                "events": [
                    {"id": "step zero", "order": 0},
                    {"id": "step one", "order": 1},
                    {"id": "step two", "order": 2},
                    {"id": "step three", "order": 3},
                ],
                "exclusions": [
                    {
                        "id": "exclusion",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    }
                ],
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
            self.assertEqual(4, len(results))
            self.assertEqual(1, results[-1]["count"])

            filters = {
                "insight": INSIGHT_FUNNELS,
                "funnel_viz_type": "steps",
                "date_from": "2024-01-10 00:00:00",
                "date_to": "2024-01-12 00:00:00",
                "events": [
                    {"id": "step zero", "order": 0},
                    {"id": "step one", "order": 1},
                    {"id": "step two", "order": 2},
                    {"id": "step three", "order": 3},
                ],
                "exclusions": [
                    {
                        "id": "exclusion",
                        "type": "events",
                        "funnel_from_step": 1,
                        "funnel_to_step": 2,
                    }
                ],
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
            self.assertEqual(4, len(results))
            self.assertEqual(1, results[-1]["count"])

        def test_first_time_for_user_funnel_filters(self):
            _create_person(
                distinct_ids=[f"user_1"],
                team=self.team,
            )

            events_by_person = {
                "user_1": [
                    {
                        "event": "$pageview",
                        "timestamp": datetime(2024, 3, 22, 13, 46),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": datetime(2024, 3, 22, 13, 47),
                        "properties": {"$browser": "Chrome"},
                    },
                ],
            }
            journeys_for(events_by_person, self.team)

            query = FunnelsQuery(
                series=[
                    EventsNode(event="$pageview"),
                    EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER),
                ],
                dateRange=DateRange(
                    date_from="2024-03-22",
                    date_to="2024-03-22",
                ),
            )
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 1)
            self.assertEqual(results[1]["count"], 0)

            query = FunnelsQuery(
                series=[
                    EventsNode(
                        event="$pageview",
                        properties=[
                            EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Chrome"),
                        ],
                        math=BaseMathType.FIRST_TIME_FOR_USER,
                    ),
                    EventsNode(event="$pageview"),
                ],
                dateRange=DateRange(
                    date_from="2024-03-22",
                    date_to="2024-03-22",
                ),
            )
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 1)
            self.assertEqual(results[1]["count"], 1)

        def test_first_time_for_user_funnel_multiple_ids(self):
            _create_person(
                distinct_ids=["user_1", "anon_1"],
                team=self.team,
            )
            _create_person(
                distinct_ids=["anon_2", "user_2"],
                team=self.team,
            )
            _create_person(
                distinct_ids=["anon_3"],
                team=self.team,
            )

            # person 1
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_1",
                timestamp="2024-03-22T13:00:00Z",
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_1",
                timestamp="2024-03-22T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="anon_1",
                timestamp="2023-03-22T13:00:00Z",
            )

            # person 2
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="anon_2",
                timestamp="2024-03-22T13:00:00Z",
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_2",
                timestamp="2024-03-22T14:00:00Z",
            )

            # person 3
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="anon_3",
                timestamp="2024-03-22T15:00:00Z",
            )

            query = FunnelsQuery(
                series=[
                    EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER),
                    EventsNode(event="$pageview"),
                ],
                dateRange=DateRange(
                    date_from="2024-03-22",
                    date_to="2024-03-22",
                ),
            )
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 2)
            self.assertEqual(results[1]["count"], 1)

            query = FunnelsQuery(
                series=[
                    EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER),
                    EventsNode(event="$pageview"),
                ],
                dateRange=DateRange(
                    date_from="2023-03-22",
                    date_to="2024-03-22",
                ),
            )
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 3)
            self.assertEqual(results[1]["count"], 1)

        def test_first_time_for_user_funnel_person_properties(self):
            _create_person(distinct_ids=["user_1"], team=self.team, properties={"email": "test@test.com"})
            _create_person(
                distinct_ids=["user_2"],
                properties={"email": "bonjonjovi@gmail.com"},
                team=self.team,
            )

            _create_event(
                team=self.team,
                event="event1",
                distinct_id="user_1",
                timestamp="2024-03-20T13:00:00Z",
            )
            _create_event(
                team=self.team,
                event="event1",
                distinct_id="user_1",
                properties={"property": "woah"},
                timestamp="2024-03-21T13:00:00Z",
            )
            _create_event(
                team=self.team,
                event="event1",
                distinct_id="user_2",
                timestamp="2024-03-22T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="event2",
                distinct_id="user_1",
                timestamp="2024-03-23T13:00:00Z",
            )

            query = FunnelsQuery(
                series=[
                    EventsNode(
                        event="event1",
                        math=FunnelMathType.FIRST_TIME_FOR_USER_WITH_FILTERS,
                        properties=[
                            EventPropertyFilter(key="property", value="woah", operator=PropertyOperator.EXACT),
                        ],
                    ),
                    EventsNode(event="event2"),
                ],
                dateRange=DateRange(
                    date_from="2024-03-20",
                    date_to="2024-03-24",
                ),
            )
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 1)
            self.assertEqual(results[1]["count"], 1)

            query.series[0].math = FunnelMathType.FIRST_TIME_FOR_USER
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
            # classic and udf funnels handle no events differently
            assert len(results) == 0 or results[0]["count"] == 0

            _create_event(
                team=self.team,
                event="event2",
                distinct_id="user_1",
                timestamp="2024-03-19T13:00:00Z",
                properties={"property": "woah"},
            )
            query.series[0].math = FunnelMathType.FIRST_TIME_FOR_USER_WITH_FILTERS
            assert query.dateRange is not None
            query.dateRange.date_from = "2024-03-19"
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
            self.assertEqual(results[0]["count"], 1)
            self.assertEqual(results[1]["count"], 1)

        def test_funnel_personless_events_are_supported(self):
            user_id = uuid.uuid4()
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=user_id,
                person_id=user_id,
                timestamp="2024-03-22T13:00:00Z",
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id=user_id,
                person_id=user_id,
                timestamp="2024-03-22T14:00:00Z",
            )

            query = FunnelsQuery(
                series=[EventsNode(event="$pageview"), EventsNode(event="sign up")],
                dateRange=DateRange(date_from="2024-03-22", date_to="2024-03-22"),
            )
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 1)
            self.assertEqual(results[1]["count"], 1)

        def test_short_exclusions(self):
            journeys_for(
                {
                    "user_one": [
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                        },
                        {
                            "event": "exclusion",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 1),
                        },
                        {
                            "event": "step two",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 31),
                        },
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 1, 1, 0, 0),
                        },
                        {
                            "event": "step two",
                            "timestamp": datetime(2021, 5, 1, 1, 0, 29),
                        },
                    ],
                },
                self.team,
            )

            filters = {
                "insight": INSIGHT_FUNNELS,
                "funnel_viz_type": "steps",
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-13 23:59:59",
                "funnel_window_interval": 30,
                "funnel_window_interval_unit": "second",
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                ],
                "exclusions": [
                    {
                        "id": "exclusion",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    }
                ],
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(1, results[1]["count"])
            self.assertEqual(29, results[1]["average_conversion_time"])

        def test_excluded_completion(self):
            events = [
                {
                    "event": "step one",
                    "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                },
                # Exclusion happens after time expires
                {
                    "event": "exclusion",
                    "timestamp": datetime(2021, 5, 1, 0, 0, 11),
                },
                {
                    "event": "step one",
                    "timestamp": datetime(2021, 5, 1, 0, 0, 12),
                },
                {
                    "event": "exclusion",
                    "timestamp": datetime(2021, 5, 1, 0, 0, 13),
                },
                {
                    "event": "step two",
                    "timestamp": datetime(2021, 5, 1, 0, 0, 14),
                },
            ]
            journeys_for(
                {
                    "user_one": events,
                },
                self.team,
            )

            filters = {
                "insight": INSIGHT_FUNNELS,
                "funnel_viz_type": "steps",
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-13 23:59:59",
                "funnel_window_interval": 10,
                "funnel_window_interval_unit": "second",
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                ],
                "exclusions": [
                    {
                        "id": "exclusion",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    }
                ],
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

            # There should be no events. UDF funnels returns an empty array and says "no events"
            # Old style funnels returns a count of 0
            try:
                self.assertEqual([], results)
            except AssertionError:
                self.assertEqual(0, results[0]["count"])
                self.assertEqual(0, results[1]["count"])

        def test_exclusion_with_property_filter(self):
            journeys_for(
                {
                    "user_excluded": [
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                        },
                        {
                            "event": "exclusion",
                            "properties": {"exclude_me": "true"},
                            "timestamp": datetime(2021, 5, 1, 0, 0, 1),
                        },
                        {
                            "event": "step two",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 2),
                        },
                    ],
                    "user_excluded_also": [
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                        },
                        {
                            "event": "exclusion",
                            "properties": {"exclude_me": "yes"},
                            "timestamp": datetime(2021, 5, 1, 0, 0, 1),
                        },
                        {
                            "event": "step two",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 2),
                        },
                    ],
                    "user_first_step": [
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                        }
                    ],
                    "user_included": [
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                        },
                        {
                            "event": "exclusion",
                            "properties": {"exclude_me": "false"},
                            "timestamp": datetime(2021, 5, 1, 0, 0, 1),
                        },
                        {
                            "event": "step two",
                            "timestamp": datetime(2021, 5, 1, 0, 0, 2),
                        },
                    ],
                },
                self.team,
            )

            query = FunnelsQuery(
                kind="FunnelsQuery",
                dateRange=DateRange(
                    date_from="2021-05-01 00:00:00",
                    date_to="2021-05-01 23:59:59",
                ),
                interval=IntervalType.DAY,
                series=[
                    EventsNode(
                        kind="EventsNode",
                        event="step one",
                        name="step one",
                    ),
                    EventsNode(
                        kind="EventsNode",
                        event="step two",
                        name="step two",
                    ),
                ],
                funnelsFilter=FunnelsFilter(
                    **{
                        "funnelVizType": FunnelVizType.STEPS,
                        "funnelWindowInterval": 10,
                        "funnelWindowIntervalUnit": FunnelConversionWindowTimeUnit.SECOND,
                        "exclusions": [
                            FunnelExclusionEventsNode(
                                kind="EventsNode",
                                event="exclusion",
                                properties=[
                                    EventPropertyFilter(
                                        key="exclude_me",
                                        value="true",
                                        operator=PropertyOperator.EXACT,
                                        type="event",
                                    )
                                ],
                                funnelFromStep=0,
                                funnelToStep=1,
                            ),
                            FunnelExclusionEventsNode(
                                kind="EventsNode",
                                event="exclusion",
                                properties=[
                                    EventPropertyFilter(
                                        key="exclude_me",
                                        value="yes",
                                        operator=PropertyOperator.EXACT,
                                        type="event",
                                    )
                                ],
                                funnelFromStep=0,
                                funnelToStep=1,
                            ),
                        ],
                    }
                ),
            )
            results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

            self.assertEqual(results[0]["count"], 2)
            self.assertEqual(results[1]["count"], 1)

        def test_breakdown_step_attributions(self):
            events = [
                {
                    "event": "step one",
                    "properties": {"$browser": "Chrome"},
                    "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                },
                {
                    "event": "step two",
                    "timestamp": datetime(2021, 5, 1, 0, 0, 1),
                    "properties": {"$browser": "Safari"},
                },
                {
                    "event": "step two",
                    "timestamp": datetime(2021, 5, 1, 0, 0, 2),
                    "properties": {"$browser": "Chrome"},
                },
                {
                    "event": "step three",
                    "timestamp": datetime(2021, 5, 1, 0, 0, 3),
                    "properties": {"$browser": "Chrome"},
                },
            ]

            journeys_for(
                {
                    "user_one": events,
                },
                self.team,
            )

            filters = {
                "insight": INSIGHT_FUNNELS,
                "funnel_viz_type": "steps",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-02 23:59:59",
                "funnel_window_interval": 30,
                "funnel_window_interval_unit": "second",
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
                "breakdown_type": "event",
                "breakdown": "$browser",
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results
            assert 1 == len(results)
            result = results[0]
            assert 3 == len(result)
            assert [x["count"] == 1 for x in result]
            assert [x["breakdown"] == ["Chrome"] for x in result]

            filters["breakdown_attribution_type"] = "all_events"
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results
            assert 1 == len(results)
            result = results[0]
            assert [x["count"] for x in result] == [1, 1, 1]
            assert [x["breakdown"] == ["Chrome"] for x in result]

            filters["breakdown_attribution_type"] = "step"
            filters["breakdown_attribution_value"] = 0
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results
            assert 1 == len(results)
            result = results[0]
            assert [x["count"] for x in result] == [1, 1, 1]
            assert [x["breakdown"] == ["Chrome"] for x in result]

            filters["breakdown_attribution_type"] = "step"
            filters["breakdown_attribution_value"] = 1
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results
            assert 2 == len(results)
            for result in results:
                assert [x["count"] for x in result] == [1, 1, 1]

            filters["breakdown_attribution_type"] = "step"
            filters["breakdown_attribution_value"] = 2
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results
            assert 1 == len(results)
            result = results[0]
            assert [x["count"] for x in result] == [1, 1, 1]
            assert [x["breakdown"] == ["Chrome"] for x in result]

        def test_funnel_with_long_interval_no_first_step(self):
            # Create a person who only completes the second step of the funnel
            person_factory(distinct_ids=["only_second_step"], team_id=self.team.pk)
            self._add_to_cart_event(distinct_id="only_second_step", timestamp=datetime(2021, 5, 2, 0, 0, 0))

            filters = {
                "insight": INSIGHT_FUNNELS,
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-08 23:59:59",
                "events": [{"id": "user signed up", "order": 0}, {"id": "added to cart", "order": 1}],
                "funnel_window_interval": 3122064000,
                "funnel_window_interval_unit": "second",
            }

            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

            if len(results) == 0:
                # This is a success - no entries.
                return

            # First step should be 0, second step should be 0 as well since the user didn't complete the first step
            self.assertEqual(results[0]["name"], "user signed up")
            self.assertEqual(results[0]["count"], 0)
            self.assertEqual(results[1]["name"], "added to cart")
            self.assertEqual(results[1]["count"], 0)

        @snapshot_clickhouse_queries
        def test_funnel_aggregation_with_groups(self):
            """Basic test for aggregation by groups."""
            self._create_groups()

            events_by_person = {
                "user_1": [
                    {
                        "event": "user signed up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$group_0": "org:5"},
                    },
                    {
                        "event": "user signed up",  # different group, so should count as a different step 1 in funnel
                        "timestamp": datetime(2020, 1, 10, 14),
                        "properties": {"$group_0": "org:6"},
                    },
                ],
                "user_2": [
                    {  # step two in funnel
                        "event": "paid",
                        "timestamp": datetime(2020, 1, 3, 14),
                        "properties": {"$group_0": "org:5"},
                    }
                ],
            }
            journeys_for(events_by_person, self.team)

            query = FunnelsQuery(
                series=[
                    EventsNode(event="user signed up"),
                    EventsNode(event="paid"),
                ],
                dateRange=DateRange(
                    date_from="2020-01-01",
                    date_to="2020-01-14",
                ),
                aggregation_group_type_index=0,
            )
            result = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

            assert result[0]["count"] == 2
            assert result[1]["count"] == 1
            assert result[1]["average_conversion_time"] == 86400

        @snapshot_clickhouse_queries
        def test_funnel_aggregation_with_groups_across_persons(self):
            """Test that aggregation by groups works across different persons."""
            self._create_groups()

            events_by_person = {
                "user_1": [
                    {
                        "event": "user signed up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$group_0": "org:5"},  # industry finance
                    },
                    {
                        "event": "paid",
                        "timestamp": datetime(2020, 1, 3, 14),
                        "properties": {
                            "$group_0": "org:6"  # industry technology
                        },  # second event belongs to different group, so shouldn't complete funnel
                    },
                ],
                "user_2": [
                    {
                        "event": "user signed up",  # event belongs to different group, so shouldn't enter funnel
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$group_0": "org:6"},
                    },
                    {
                        "event": "paid",
                        "timestamp": datetime(2020, 1, 3, 14),
                        "properties": {"$group_0": "org:5"},  # same group, so should complete funnel
                    },
                ],
            }
            journeys_for(events_by_person, self.team)

            query = FunnelsQuery(
                series=[
                    EventsNode(event="user signed up"),
                    EventsNode(event="paid"),
                ],
                dateRange=DateRange(
                    date_from="2020-01-01",
                    date_to="2020-01-14",
                ),
                aggregation_group_type_index=0,
                properties=[
                    GroupPropertyFilter(
                        key="industry",
                        value="finance",
                        type="group",
                        group_type_index=0,
                        operator=PropertyOperator.EXACT,
                    )
                ],
            )
            result = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

            assert result[0]["count"] == 1
            assert result[1]["count"] == 1

        def test_funnel_aggregation_with_groups_and_ungrouped_events(self):
            """Test that ungrouped events don't get lumped together, and are filtered out instead."""
            self._create_groups()

            events_by_person = {
                "user_1": [
                    {
                        "event": "user signed up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$group_0": "org:5"},
                    },
                    {
                        "event": "paid",
                        "timestamp": datetime(2020, 1, 3, 14),
                        "properties": {"$group_0": "org:5"},
                    },
                ],
                "user_2": [
                    {
                        "event": "user signed up",
                        "timestamp": datetime(2020, 1, 2, 14),
                    },
                ],
                "user_3": [
                    {
                        "event": "paid",
                        "timestamp": datetime(2020, 1, 3, 14),
                    },
                ],
                "user_4": [
                    {
                        "event": "user signed up",
                        "timestamp": datetime(2020, 1, 2, 14),
                    },
                    {
                        "event": "paid",
                        "timestamp": datetime(2020, 1, 3, 14),
                    },
                ],
            }
            journeys_for(events_by_person, self.team)

            query = FunnelsQuery(
                series=[
                    EventsNode(event="user signed up"),
                    EventsNode(event="paid"),
                ],
                dateRange=DateRange(
                    date_from="2020-01-01",
                    date_to="2020-01-14",
                ),
                aggregation_group_type_index=0,
            )
            result = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

            assert result[0]["count"] == 1
            assert result[1]["count"] == 1

    return TestGetFunnel


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=False))
class TestFOSSFunnel(funnel_test_factory(Funnel, _create_event, _create_person)):  # type: ignore
    maxDiff = None


class TestFunnelStepCountsWithoutAggregationQuery(BaseTest):
    maxDiff = None

    def test_smoke(self):
        with freeze_time("2024-01-10T12:01:00"):
            query = FunnelsQuery(series=[EventsNode(), EventsNode()])
            funnel_class = Funnel(context=FunnelQueryContext(query=query, team=self.team))

        query_ast = funnel_class.get_step_counts_without_aggregation_query()
        response = execute_hogql_query(query_type="FunnelsQuery", query=query_ast, team=self.team)

        self.assertEqual(
            response.hogql,
            """SELECT
    aggregation_target,
    timestamp,
    step_0,
    latest_0,
    step_1,
    latest_1,
    if(and(less(latest_0, latest_1), lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14)))), 2, 1) AS steps,
    if(and(isNotNull(latest_1), lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14)))), dateDiff('second', latest_0, latest_1), NULL) AS step_1_conversion_time
FROM
    (SELECT
        aggregation_target,
        timestamp,
        step_0,
        latest_0,
        step_1,
        min(latest_1) OVER (PARTITION BY aggregation_target ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS latest_1
    FROM
        (SELECT
            e.timestamp AS timestamp,
            person_id AS aggregation_target,
            if(1, 1, 0) AS step_0,
            if(equals(step_0, 1), timestamp, NULL) AS latest_0,
            if(1, 1, 0) AS step_1,
            if(equals(step_1, 1), timestamp, NULL) AS latest_1
        FROM
            events AS e
        WHERE
            and(and(greaterOrEquals(e.timestamp, toDateTime('2024-01-03 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2024-01-10 23:59:59.999999'))), or(equals(step_0, 1), equals(step_1, 1)))))
WHERE
    equals(step_0, 1)
LIMIT 100""",
        )


class TestFunnelStepCountsQuery(BaseTest):
    maxDiff = None

    def test_smoke(self):
        with freeze_time("2024-01-10T12:01:00"):
            query = FunnelsQuery(series=[EventsNode(), EventsNode()])
            funnel_class = Funnel(context=FunnelQueryContext(query=query, team=self.team))

        query_ast = funnel_class.get_step_counts_query()
        response = execute_hogql_query(query_type="FunnelsQuery", query=query_ast, team=self.team)

        self.assertEqual(
            response.hogql,
            """SELECT
    aggregation_target,
    steps,
    avg(step_1_conversion_time) AS step_1_average_conversion_time_inner,
    median(step_1_conversion_time) AS step_1_median_conversion_time_inner
FROM
    (SELECT
        aggregation_target,
        steps,
        max(steps) OVER (PARTITION BY aggregation_target) AS max_steps,
        step_1_conversion_time
    FROM
        (SELECT
            aggregation_target,
            timestamp,
            step_0,
            latest_0,
            step_1,
            latest_1,
            if(and(less(latest_0, latest_1), lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14)))), 2, 1) AS steps,
            if(and(isNotNull(latest_1), lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14)))), dateDiff('second', latest_0, latest_1), NULL) AS step_1_conversion_time
        FROM
            (SELECT
                aggregation_target,
                timestamp,
                step_0,
                latest_0,
                step_1,
                min(latest_1) OVER (PARTITION BY aggregation_target ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS latest_1
            FROM
                (SELECT
                    e.timestamp AS timestamp,
                    person_id AS aggregation_target,
                    if(1, 1, 0) AS step_0,
                    if(equals(step_0, 1), timestamp, NULL) AS latest_0,
                    if(1, 1, 0) AS step_1,
                    if(equals(step_1, 1), timestamp, NULL) AS latest_1
                FROM
                    events AS e
                WHERE
                    and(and(greaterOrEquals(e.timestamp, toDateTime('2024-01-03 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2024-01-10 23:59:59.999999'))), or(equals(step_0, 1), equals(step_1, 1)))))
        WHERE
            equals(step_0, 1)))
GROUP BY
    aggregation_target,
    steps
HAVING
    equals(steps, max(max_steps))
LIMIT 100""",
        )


class TestFunnelQuery(BaseTest):
    maxDiff = None

    def test_smoke(self):
        with freeze_time("2024-01-10T12:01:00"):
            query = FunnelsQuery(series=[EventsNode(), EventsNode()])
            funnel_class = Funnel(context=FunnelQueryContext(query=query, team=self.team))

        query_ast = funnel_class.get_query()
        response = execute_hogql_query(query_type="FunnelsQuery", query=query_ast, team=self.team)

        self.assertEqual(
            response.hogql,
            """SELECT
    countIf(equals(steps, 1)) AS step_1,
    countIf(equals(steps, 2)) AS step_2,
    avg(step_1_average_conversion_time_inner) AS step_1_average_conversion_time,
    median(step_1_median_conversion_time_inner) AS step_1_median_conversion_time
FROM
    (SELECT
        aggregation_target,
        steps,
        avg(step_1_conversion_time) AS step_1_average_conversion_time_inner,
        median(step_1_conversion_time) AS step_1_median_conversion_time_inner
    FROM
        (SELECT
            aggregation_target,
            steps,
            max(steps) OVER (PARTITION BY aggregation_target) AS max_steps,
            step_1_conversion_time
        FROM
            (SELECT
                aggregation_target,
                timestamp,
                step_0,
                latest_0,
                step_1,
                latest_1,
                if(and(less(latest_0, latest_1), lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14)))), 2, 1) AS steps,
                if(and(isNotNull(latest_1), lessOrEquals(latest_1, plus(toTimeZone(latest_0, 'UTC'), toIntervalDay(14)))), dateDiff('second', latest_0, latest_1), NULL) AS step_1_conversion_time
            FROM
                (SELECT
                    aggregation_target,
                    timestamp,
                    step_0,
                    latest_0,
                    step_1,
                    min(latest_1) OVER (PARTITION BY aggregation_target ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS latest_1
                FROM
                    (SELECT
                        e.timestamp AS timestamp,
                        person_id AS aggregation_target,
                        if(1, 1, 0) AS step_0,
                        if(equals(step_0, 1), timestamp, NULL) AS latest_0,
                        if(1, 1, 0) AS step_1,
                        if(equals(step_1, 1), timestamp, NULL) AS latest_1
                    FROM
                        events AS e
                    WHERE
                        and(and(greaterOrEquals(e.timestamp, toDateTime('2024-01-03 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2024-01-10 23:59:59.999999'))), or(equals(step_0, 1), equals(step_1, 1)))))
            WHERE
                equals(step_0, 1)))
    GROUP BY
        aggregation_target,
        steps
    HAVING
        equals(steps, max(max_steps)))
LIMIT 100""",
        )
