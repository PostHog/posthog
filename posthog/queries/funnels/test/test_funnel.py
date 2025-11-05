import uuid
from datetime import datetime

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    create_person_id_override_by_distinct_id,
    snapshot_clickhouse_queries,
)
from unittest.case import skip

from django.test import override_settings

from rest_framework.exceptions import ValidationError

from posthog.clickhouse.client import sync_execute
from posthog.constants import FILTER_TEST_ACCOUNTS, INSIGHT_FUNNELS
from posthog.models import Action, Element
from posthog.models.cohort import Cohort
from posthog.models.filters import Filter
from posthog.models.instance_setting import get_instance_setting
from posthog.queries.funnels import ClickhouseFunnel, ClickhouseFunnelActors
from posthog.queries.funnels.test.breakdown_cases import assert_funnel_results_equal, funnel_breakdown_test_factory
from posthog.queries.funnels.test.conversion_time_cases import funnel_conversion_time_test_factory
from posthog.test.test_journeys import journeys_for


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": name, "properties": properties}])
    return action


class TestFunnelBreakdown(
    ClickhouseTestMixin,
    funnel_breakdown_test_factory(
        ClickhouseFunnel,
        ClickhouseFunnelActors,
        _create_event,
        _create_action,
        _create_person,
    ),
):
    maxDiff = None
    pass


class TestFunnelConversionTime(
    ClickhouseTestMixin,
    funnel_conversion_time_test_factory(ClickhouseFunnel, ClickhouseFunnelActors, _create_event, _create_person),
):
    maxDiff = None
    pass


def funnel_test_factory(Funnel, event_factory, person_factory):
    class TestGetFunnel(ClickhouseTestMixin, APIBaseTest):
        def _get_actor_ids_at_step(self, filter, funnel_step, breakdown_value=None):
            person_filter = filter.shallow_clone({"funnel_step": funnel_step, "funnel_step_breakdown": breakdown_value})
            _, serialized_result, _ = ClickhouseFunnelActors(person_filter, self.team).get_actors()

            return [val["id"] for val in serialized_result]

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

        def _single_step_funnel(self, properties=None, filters=None):
            if filters is None:
                filters = {
                    "events": [{"id": "user signed up", "type": "events", "order": 0}],
                    "insight": INSIGHT_FUNNELS,
                    "funnel_window_days": 14,
                }

            if properties is not None:
                filters.update({"properties": properties})

            filter = Filter(data=filters)
            return Funnel(filter=filter, team=self.team)

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
            filter = Filter(data=filters, team=self.team)
            return Funnel(filter=filter, team=self.team)

        def test_funnel_default(self):
            funnel = self._single_step_funnel()

            with freeze_time("2012-01-01T03:21:34.000Z"):
                # event
                person_factory(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
                self._signup_event(distinct_id="stopped_after_signup1")

                person_factory(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
                self._signup_event(distinct_id="stopped_after_signup2")

            result = funnel.run()
            self.assertEqual(result[0]["count"], 0)

        def test_funnel_with_single_step(self):
            funnel = self._single_step_funnel()

            # event
            person_factory(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_signup1")

            person_factory(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_signup2")

            result = funnel.run()
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 2)

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

            result = funnel.run()
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
                result = funnel.run()
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

            result = funnel.run()
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

            result = funnel.run()
            self.assertEqual(result[0]["name"], None)
            self.assertEqual(result[0]["count"], 5)

            self.assertEqual(result[1]["name"], None)
            self.assertEqual(result[1]["count"], 3)

            self.assertEqual(result[2]["name"], None)
            self.assertEqual(result[2]["count"], 1)

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

            result = funnel.run()
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 4)

            self.assertEqual(result[1]["name"], "watched movie")
            self.assertEqual(result[1]["count"], 1)

        def test_funnel_no_events(self):
            funnel = Funnel(filter=Filter(data={"some": "prop"}), team=self.team)
            self.assertEqual(funnel.run(), [])

        def test_funnel_skipped_step(self):
            funnel = self._basic_funnel()

            person_factory(distinct_ids=["wrong_order"], team_id=self.team.pk)
            self._signup_event(distinct_id="wrong_order")
            self._movie_event(distinct_id="wrong_order")

            result = funnel.run()
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

            result = funnel.run()
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

            result = funnel.run()

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

            result = funnel.run()
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

            result = Funnel(
                filter=Filter(
                    data={
                        "events": [{"id": "event1", "order": 0}],
                        "actions": [
                            {"id": action1.pk, "order": 1},
                            {"id": action2.pk, "order": 2},
                        ],
                        "insight": INSIGHT_FUNNELS,
                        "funnel_window_days": 14,
                    }
                ),
                team=self.team,
            ).run()
            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(result[1]["count"], 1)
            self.assertEqual(result[2]["count"], 0)

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
            result = Funnel(
                filter=Filter(
                    data={
                        "events": [{"id": "event1", "order": 0}],
                        "insight": INSIGHT_FUNNELS,
                        FILTER_TEST_ACCOUNTS: True,
                        "funnel_window_days": 14,
                    },
                    team=self.team,
                ),
                team=self.team,
            ).run()
            self.assertEqual(result[0]["count"], 1)

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

            result = Funnel(
                filter=Filter(
                    data={
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
                            }
                        ],
                        "insight": INSIGHT_FUNNELS,
                        "funnel_window_days": 14,
                    }
                ),
                team=self.team,
            ).run()
            self.assertEqual(result[0]["count"], 2)

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

            result = Funnel(
                filter=Filter(
                    data={
                        "actions": [{"id": action.pk, "type": "actions", "order": 0}],
                        "insight": INSIGHT_FUNNELS,
                        "funnel_window_days": 14,
                    }
                ),
                team=self.team,
            ).run()

            self.assertEqual(result[0]["count"], 2)

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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 1)

            self.assertEqual(result[1]["name"], "paid")
            self.assertEqual(result[1]["count"], 1)

        def test_basic_funnel_with_repeat_steps(self):
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "user signed up", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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

            result = funnel.run()
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 2)

            self.assertEqual(result[1]["count"], 1)

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2),
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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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

            result = funnel.run()
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 2)

            self.assertEqual(result[1]["count"], 1)

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2),
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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)
            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 2)

            self.assertEqual(result[1]["count"], 1)

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1),
                [
                    people["stopped_after_signup1"].uuid,
                    people["stopped_after_signup2"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2),
                [people["stopped_after_signup1"].uuid],
            )

            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "user signed up", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_interval": 2,
                "funnel_window_interval_unit": "week",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)
            result2 = funnel.run()

            assert_funnel_results_equal(result, result2)

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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)
            result3 = funnel.run()

            assert_funnel_results_equal(result, result3)

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
            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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

            result = funnel.run()
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 2)

            self.assertEqual(result[1]["name"], "paid")
            self.assertEqual(result[1]["count"], 2)

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1), [person1.uuid, person3.uuid])
            self.assertCountEqual(self._get_actor_ids_at_step(filter, 2), [person1.uuid, person3.uuid])

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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 2)

            self.assertEqual(result[4]["count"], 2)

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1), [person1.uuid, person2.uuid])

            filter = filter.shallow_clone(
                {
                    "exclusions": [
                        {
                            "id": "x",
                            "type": "events",
                            "funnel_from_step": 1,
                            "funnel_to_step": 2,
                        }
                    ]
                }
            )
            funnel = Funnel(filter, self.team)

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 2)

            self.assertEqual(result[4]["count"], 2)

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1), [person2.uuid, person3.uuid])

            filter = filter.shallow_clone(
                {
                    "exclusions": [
                        {
                            "id": "x",
                            "type": "events",
                            "funnel_from_step": 2,
                            "funnel_to_step": 3,
                        }
                    ]
                }
            )
            funnel = Funnel(filter, self.team)

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 1)

            self.assertEqual(result[4]["count"], 1)

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1), [person3.uuid])

            filter = filter.shallow_clone(
                {
                    "exclusions": [
                        {
                            "id": "x",
                            "type": "events",
                            "funnel_from_step": 3,
                            "funnel_to_step": 4,
                        }
                    ]
                }
            )
            funnel = Funnel(filter, self.team)

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 0)

            self.assertEqual(result[4]["count"], 0)

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1), [])

            #  bigger step window
            filter = filter.shallow_clone(
                {
                    "exclusions": [
                        {
                            "id": "x",
                            "type": "events",
                            "funnel_from_step": 1,
                            "funnel_to_step": 3,
                        }
                    ]
                }
            )
            funnel = Funnel(filter, self.team)

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 1)

            self.assertEqual(result[4]["count"], 1)

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1), [person3.uuid])

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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[1]["name"], "$pageview")
            self.assertEqual(result[4]["name"], "$pageview")
            self.assertEqual(result[0]["count"], 5)

            self.assertEqual(result[1]["count"], 4)

            self.assertEqual(result[2]["count"], 3)

            self.assertEqual(result[3]["count"], 2)

            self.assertEqual(result[4]["count"], 1)

            # check ordering of people in every step
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1),
                [
                    people["stopped_after_signup1"].uuid,
                    people["stopped_after_pageview1"].uuid,
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2),
                [
                    people["stopped_after_pageview1"].uuid,
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 3),
                [
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 4),
                [
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 5),
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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[1]["name"], "$pageview")
            self.assertEqual(result[4]["name"], "$pageview")
            self.assertEqual(result[0]["count"], 5)

            self.assertEqual(result[1]["count"], 4)

            self.assertEqual(result[2]["count"], 1)

            self.assertEqual(result[3]["count"], 1)

            self.assertEqual(result[4]["count"], 1)

            # check ordering of people in every step
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1),
                [
                    person1_stopped_after_signup.uuid,
                    person2_stopped_after_one_pageview.uuid,
                    person3_stopped_after_two_pageview.uuid,
                    person4_stopped_after_three_pageview.uuid,
                    person5_stopped_after_many_pageview.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2),
                [
                    person2_stopped_after_one_pageview.uuid,
                    person3_stopped_after_two_pageview.uuid,
                    person4_stopped_after_three_pageview.uuid,
                    person5_stopped_after_many_pageview.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 3),
                [person5_stopped_after_many_pageview.uuid],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 4),
                [person5_stopped_after_many_pageview.uuid],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 5),
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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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

            result = funnel.run()

            self.assertEqual(result[0]["name"], "sign up")
            self.assertEqual(result[0]["count"], 2)

            self.assertEqual(result[1]["count"], 1)

            # check ordering of people in first step
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2),
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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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

                result = funnel.run()

                self.assertEqual(result[0]["name"], "sign up")
                self.assertEqual(result[0]["count"], 2)

                self.assertEqual(result[1]["count"], 1)

                # check ordering of people in first step
                self.assertCountEqual(
                    self._get_actor_ids_at_step(filter, 1),
                    [
                        person1_stopped_after_two_signups.uuid,
                        person2_stopped_after_signup.uuid,
                    ],
                )

                self.assertCountEqual(
                    self._get_actor_ids_at_step(filter, 2),
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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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

            result = funnel.run()

            self.assertEqual(result[0]["name"], "sign up")
            self.assertEqual(result[0]["count"], 2)

            self.assertEqual(result[1]["count"], 1)

            # check ordering of people in first step
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2),
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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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

            result = funnel.run()

            self.assertEqual(result[0]["name"], "sign up")
            self.assertEqual(result[0]["count"], 2)

            self.assertEqual(result[1]["count"], 1)

            # check ordering of people in first step
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2),
                [person1_stopped_after_two_signups.uuid],
            )

        @also_test_with_materialized_columns(["key"])
        @skip("Flaky funnel test")
        def test_funnel_with_actions_and_events(self):
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
                    {"id": "user signed up", "type": "events", "order": 1},
                ],
                "actions": [
                    {"id": sign_up_action.id, "math": "dau", "order": 2},
                    {"id": sign_up_action.id, "math": "weekly_active", "order": 3},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 14,
            }

            filter = Filter(data=filters, team=self.team)

            # event
            person1_stopped_after_two_signups = _create_person(
                distinct_ids=["stopped_after_signup1"], team_id=self.team.pk
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_signup1",
                timestamp="2021-05-01 00:00:00",
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_signup1",
                timestamp="2021-05-01 00:00:01",
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="stopped_after_signup1",
                properties={"key": "val"},
                timestamp="2021-05-01 00:00:02",
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="stopped_after_signup1",
                properties={"key": "val"},
                timestamp="2021-05-01 00:00:03",
            )

            person2_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_signup2",
                timestamp="2021-05-01 00:00:04",
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_signup2",
                timestamp="2021-05-01 00:00:05",
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="stopped_after_signup2",
                properties={"key": "val"},
                timestamp="2021-05-01 00:00:06",
            )

            person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person3",
                timestamp="2021-05-01 00:00:07",
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person3",
                properties={"key": "val"},
                timestamp="2021-05-01 00:00:08",
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person3",
                timestamp="2021-05-01 00:00:09",
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person3",
                properties={"key": "val"},
                timestamp="2021-05-01 00:00:10",
            )

            person4 = _create_person(distinct_ids=["person4"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person4",
                timestamp="2021-05-01 00:00:11",
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person4",
                properties={"key": "val"},
                timestamp="2021-05-01 00:00:12",
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="person4",
                timestamp="2021-05-01 00:00:13",
            )

            _create_person(distinct_ids=["person5"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person5",
                properties={"key": "val"},
                timestamp="2021-05-01 00:00:14",
            )

            with freeze_time("2021-05-02"):
                result = Funnel(filter, self.team).run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 4)
            self.assertEqual(result[1]["count"], 4)
            self.assertEqual(result[2]["count"], 3)
            self.assertEqual(result[3]["count"], 1)

            # check ordering of people in steps
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                    person3.uuid,
                    person4.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                    person3.uuid,
                    person4.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 3),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                    person3.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 4),
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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[1]["name"], "$pageview")
            self.assertEqual(result[4]["name"], "$pageview")
            self.assertEqual(result[0]["count"], 5)
            self.assertEqual(result[1]["count"], 4)
            self.assertEqual(result[2]["count"], 3)
            self.assertEqual(result[3]["count"], 2)
            self.assertEqual(result[4]["count"], 0)
            # check ordering of people in every step
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1),
                [
                    people["stopped_after_signup1"].uuid,
                    people["stopped_after_pageview1"].uuid,
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2),
                [
                    people["stopped_after_pageview1"].uuid,
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 3),
                [
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 4),
                [
                    people["stopped_after_pageview3"].uuid,
                    people["stopped_after_pageview4"].uuid,
                ],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 5), [])

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

            data = {
                "insight": INSIGHT_FUNNELS,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-14 00:00:00",
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }

            filter = Filter(data={**data})
            results = Funnel(filter, self.team).run()

            self.assertEqual(results[0]["count"], 25)
            self.assertEqual(results[1]["count"], 10)
            self.assertEqual(results[2]["count"], 0)

            self.assertCountEqual(
                [str(id) for id in self._get_actor_ids_at_step(filter, 2)],
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

            data = {
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

            filter = Filter(data={**data})
            results = Funnel(filter, self.team).run()

            self.assertEqual(results[0]["count"], 25)
            self.assertEqual(results[1]["count"], 10)
            self.assertEqual(results[2]["count"], 0)

            self.assertCountEqual(
                [str(id) for id in self._get_actor_ids_at_step(filter, 2)],
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
            filter = Filter(data=filters)
            self.assertRaises(ValidationError, lambda: Funnel(filter, self.team))

            filter = filter.shallow_clone(
                {
                    "exclusions": [
                        {
                            "id": "x",
                            "type": "events",
                            "funnel_from_step": 1,
                            "funnel_to_step": 2,
                        }
                    ]
                }
            )
            self.assertRaises(ValidationError, lambda: Funnel(filter, self.team))

            filter = filter.shallow_clone(
                {
                    "exclusions": [
                        {
                            "id": "x",
                            "type": "events",
                            "funnel_from_step": 2,
                            "funnel_to_step": 1,
                        }
                    ]
                }
            )
            self.assertRaises(ValidationError, lambda: Funnel(filter, self.team))

            filter = filter.shallow_clone(
                {
                    "exclusions": [
                        {
                            "id": "x",
                            "type": "events",
                            "funnel_from_step": 0,
                            "funnel_to_step": 2,
                        }
                    ]
                }
            )
            self.assertRaises(ValidationError, lambda: Funnel(filter, self.team))

        def test_funnel_exclusion_no_end_event(self):
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_days": 1,
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
            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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

            # event 3
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

            # event 4 - outside conversion window
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

            result = funnel.run()
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 2)

            self.assertEqual(result[1]["name"], "paid")
            self.assertEqual(result[1]["count"], 1)

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1), [person1.uuid, person4.uuid])
            self.assertCountEqual(self._get_actor_ids_at_step(filter, 2), [person1.uuid])

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
            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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

            result = funnel.run()
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 2)

            self.assertEqual(result[1]["name"], "paid")
            self.assertEqual(result[1]["count"], 2)

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1), [person1.uuid, person3.uuid])
            self.assertCountEqual(self._get_actor_ids_at_step(filter, 2), [person1.uuid, person3.uuid])

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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 1)

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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 1)

            self.assertEqual(result[4]["count"], 1)

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1), [person4.uuid])

            filter = filter.shallow_clone(
                {
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
                    ]
                }
            )
            funnel = Funnel(filter, self.team)

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 1)

            self.assertEqual(result[4]["count"], 1)

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1), [person4.uuid])

            filter = filter.shallow_clone(
                {
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
                    ]
                }
            )
            funnel = Funnel(filter, self.team)

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 1)

            self.assertEqual(result[4]["count"], 1)

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1), [person4.uuid])

            filter = filter.shallow_clone(
                {
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
                    ]
                }
            )
            funnel = Funnel(filter, self.team)

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 1)

            self.assertEqual(result[4]["count"], 1)

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1), [person4.uuid])

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

                filter = Filter(data=filters)
                result = Funnel(filter, self.team).run()

                self.assertEqual(len(result), 2)
                self.assertEqual(result[0]["name"], "user signed up")
                self.assertEqual(result[0]["count"], 2)

                self.assertEqual(result[1]["name"], "$autocapture")
                self.assertEqual(result[1]["count"], 1)

                self.assertCountEqual(self._get_actor_ids_at_step(filter, 1), [person1.uuid, person2.uuid])
                self.assertCountEqual(self._get_actor_ids_at_step(filter, 2), [person1.uuid])

        def test_breakdown_values_is_set_on_the_query_with_fewer_than_two_entities(self):
            filter_with_breakdown = {
                "events": [{"id": "with one entity", "type": "events", "order": 0}],
                "breakdown": "something",
            }

            try:
                ClickhouseFunnel(Filter(data=filter_with_breakdown), self.team).run()
            except KeyError as ke:
                raise AssertionError(f"Should not have raised a key error: {ke}")

        @snapshot_clickhouse_queries
        def test_funnel_with_cohorts_step_filter(self):
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
                        "properties": [{"type": "cohort", "key": "id", "value": cohort.pk}],
                    },
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-14",
            }

            result = ClickhouseFunnel(Filter(data=filters), self.team).run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 1)

            self.assertEqual(result[1]["name"], "paid")
            self.assertEqual(result[1]["count"], 1)

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
                result = ClickhouseFunnel(Filter(data=filters), self.team).run()
                self.assertEqual(result[0]["name"], "user signed up")
                self.assertEqual(result[0]["count"], 1)

                self.assertEqual(result[1]["name"], "paid")
                self.assertEqual(result[1]["count"], 1)

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

            result = ClickhouseFunnel(Filter(data=filters), self.team).run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 1)

            self.assertEqual(result[1]["name"], "paid")
            self.assertEqual(result[1]["count"], 1)

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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

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
                        # {"event": "user signed up"}, # no signup, so not in funnel
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

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[1]["name"], "$pageview")
            self.assertEqual(result[2]["name"], "$pageview")
            self.assertEqual(result[0]["count"], 3)
            self.assertEqual(result[1]["count"], 2)
            self.assertEqual(result[2]["count"], 1)
            # check ordering of people in every step
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1),
                [
                    people["stopped_after_pageview1"].uuid,
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2),
                [
                    people["stopped_after_pageview2"].uuid,
                    people["stopped_after_pageview3"].uuid,
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 3),
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

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            _create_person(distinct_ids=["user_1"], team_id=self.team.pk)
            #  this event shouldn't appear as in US/Pacific this would be the previous day
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="user_1",
                timestamp="2020-01-01T01:00:00Z",
            )
            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 0)

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

            result = funnel.run()
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 4)

            self.assertEqual(result[1]["name"], "watched movie")
            self.assertEqual(result[1]["count"], 1)

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
            result = self._basic_funnel(filters=basic_filters).run()
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 2)
            self.assertEqual(result[1]["count"], 1)
            self.assertEqual(result[2]["count"], 1)

            # properties.$session_id
            result = self._basic_funnel(
                filters={
                    **basic_filters,
                    "funnel_aggregate_by_hogql": "properties.$session_id",
                }
            ).run()
            self.assertEqual(result[0]["count"], 3)
            self.assertEqual(result[1]["count"], 2)
            self.assertEqual(result[2]["count"], 1)

            # distinct_id
            result = self._basic_funnel(filters={**basic_filters, "funnel_aggregate_by_hogql": "distinct_id"}).run()
            self.assertEqual(result[0]["count"], 2)
            self.assertEqual(result[1]["count"], 1)
            self.assertEqual(result[2]["count"], 1)

            # person_id
            result = self._basic_funnel(filters={**basic_filters, "funnel_aggregate_by_hogql": "person_id"}).run()
            self.assertEqual(result[0]["count"], 2)
            self.assertEqual(result[1]["count"], 1)
            self.assertEqual(result[2]["count"], 1)

            # # person.properties.common_prop - not supported!
            # result = self._basic_funnel(
            #     filters={**basic_filters, "funnel_aggregate_by_hogql": "person.properties.common_prop"}
            # ).run()
            # self.assertEqual(result[0]["count"], 1)
            # self.assertEqual(result[1]["count"], 1)
            # self.assertEqual(result[2]["count"], 1)

        def test_funnel_all_events_with_properties(self):
            person_factory(distinct_ids=["user"], team_id=self.team.pk)
            self._signup_event(distinct_id="user")
            self._add_to_cart_event(distinct_id="user", properties={"is_saved": True})

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

            result = self._basic_funnel(filters=filters).run()
            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(result[1]["count"], 1)

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

            result = self._basic_funnel(filters=filters).run()
            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(result[1]["count"], 1)

        def test_funnel_personless_events_are_supported(self):
            personless_user = uuid.uuid4()
            self._signup_event(distinct_id=personless_user, person_id=personless_user)
            self._add_to_cart_event(distinct_id=personless_user, person_id=personless_user)

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
                        "id": "added to cart",
                        "order": 1,
                        "name": "added to cart",
                        "math": "total",
                    },
                ],
                "funnel_window_days": 14,
            }

            result = self._basic_funnel(filters=filters).run()
            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(result[1]["count"], 1)

    return TestGetFunnel


class TestFOSSFunnel(funnel_test_factory(ClickhouseFunnel, _create_event, _create_person)):
    maxDiff = None
