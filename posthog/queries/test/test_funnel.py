from unittest.mock import patch

from freezegun import freeze_time

from posthog.constants import FILTER_TEST_ACCOUNTS, INSIGHT_FUNNELS
from posthog.models import Action, ActionStep, Element, Event, Person
from posthog.models.filters import Filter
from posthog.queries.funnel import Funnel
from posthog.tasks.calculate_action import calculate_actions_from_last_calculation
from posthog.tasks.update_cache import update_cache_item
from posthog.test.base import APIBaseTest, test_with_materialized_columns


def funnel_test_factory(Funnel, event_factory, person_factory):
    @patch("posthog.celery.update_cache_item_task.delay", update_cache_item)
    class TestGetFunnel(APIBaseTest):
        def _signup_event(self, **kwargs):
            event_factory(team=self.team, event="user signed up", **kwargs)

        def _pay_event(self, **kwargs):
            event_factory(
                team=self.team,
                event="$autocapture",
                elements=[Element(nth_of_type=1, nth_child=0, tag_name="button", text="Pay $10")],
                **kwargs
            )

        def _movie_event(self, **kwargs):
            event_factory(
                team=self.team,
                event="$autocapture",
                elements=[Element(nth_of_type=1, nth_child=0, tag_name="a", href="/movie")],
                **kwargs
            )

        def _single_step_funnel(self, properties=None, filters=None):
            if filters is None:
                filters = {
                    "events": [{"id": "user signed up", "type": "events", "order": 0},],
                    "insight": INSIGHT_FUNNELS,
                    "funnel_window_days": 14,
                }

            if properties is not None:
                filters.update({"properties": properties})

            filter = Filter(data=filters)
            return Funnel(filter=filter, team=self.team)

        def _basic_funnel(self, properties=None, filters=None):
            action_credit_card = Action.objects.create(team=self.team, name="paid")
            ActionStep.objects.create(
                action=action_credit_card, event="$autocapture", tag_name="button", text="Pay $10"
            )
            action_play_movie = Action.objects.create(team=self.team, name="watched movie")
            ActionStep.objects.create(action=action_play_movie, event="$autocapture", tag_name="a", href="/movie")

            if filters is None:
                filters = {
                    "events": [{"id": "user signed up", "type": "events", "order": 0},],
                    "actions": [
                        {"id": action_credit_card.pk, "type": "actions", "order": 1},
                        {"id": action_play_movie.pk, "type": "actions", "order": 2},
                    ],
                    "funnel_window_days": 14,
                }

            if properties is not None:
                filters.update({"properties": properties})

            filters["insight"] = INSIGHT_FUNNELS
            filter = Filter(data=filters)
            return Funnel(filter=filter, team=self.team)

        def test_funnel_default(self):
            funnel = self._single_step_funnel()

            with freeze_time("2012-01-01T03:21:34.000Z"):
                # event
                person1_stopped_after_signup = person_factory(
                    distinct_ids=["stopped_after_signup1"], team_id=self.team.pk
                )
                self._signup_event(distinct_id="stopped_after_signup1")

                person2_stopped_after_signup = person_factory(
                    distinct_ids=["stopped_after_signup2"], team_id=self.team.pk
                )
                self._signup_event(distinct_id="stopped_after_signup2")

            with self.assertNumQueries(1):
                result = funnel.run()
            self.assertEqual(result[0]["count"], 0)

        def test_funnel_with_single_step(self):
            funnel = self._single_step_funnel()

            # event
            person1_stopped_after_signup = person_factory(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_signup1")

            person2_stopped_after_signup = person_factory(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_signup2")

            with self.assertNumQueries(1):
                result = funnel.run()
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 2)

        def test_funnel_events(self):
            funnel = self._basic_funnel()

            # events
            person_stopped_after_signup = person_factory(distinct_ids=["stopped_after_signup"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_signup")

            person_stopped_after_pay = person_factory(distinct_ids=["stopped_after_pay"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_pay")
            self._pay_event(distinct_id="stopped_after_pay")

            person_stopped_after_movie = person_factory(
                distinct_ids=["had_anonymous_id", "completed_movie"], team_id=self.team.pk
            )
            self._signup_event(distinct_id="had_anonymous_id")
            self._pay_event(distinct_id="completed_movie")
            self._movie_event(distinct_id="completed_movie")

            person_that_just_did_movie = person_factory(distinct_ids=["just_did_movie"], team_id=self.team.pk)
            self._movie_event(distinct_id="just_did_movie")

            person_wrong_order = person_factory(distinct_ids=["wrong_order"], team_id=self.team.pk)
            self._pay_event(distinct_id="wrong_order")
            self._signup_event(distinct_id="wrong_order")
            self._movie_event(distinct_id="wrong_order")

            self._signup_event(distinct_id="a_user_that_got_deleted_or_doesnt_exist")

            calculate_actions_from_last_calculation()

            result = funnel.run()
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 4)

            self.assertEqual(result[1]["name"], "paid")
            self.assertEqual(result[1]["count"], 2)
            self.assertEqual(result[2]["name"], "watched movie")
            self.assertEqual(result[2]["count"], 1)

            # make sure it's O(n)
            person_wrong_order = person_factory(distinct_ids=["badalgo"], team_id=self.team.pk)
            self._signup_event(distinct_id="badalgo")
            with self.assertNumQueries(3):
                funnel.run()

            self._pay_event(distinct_id="badalgo")
            with self.assertNumQueries(3):
                funnel.run()

        def test_funnel_no_events(self):
            funnel = Funnel(filter=Filter(data={"some": "prop"}), team=self.team)
            self.assertEqual(funnel.run(), [])

        def test_funnel_skipped_step(self):
            funnel = self._basic_funnel()

            person_wrong_order = person_factory(distinct_ids=["wrong_order"], team_id=self.team.pk)
            self._signup_event(distinct_id="wrong_order")
            self._movie_event(distinct_id="wrong_order")

            result = funnel.run()
            self.assertEqual(result[1]["count"], 0)
            self.assertEqual(result[2]["count"], 0)

        @test_with_materialized_columns(["$browser"])
        def test_funnel_prop_filters(self):
            funnel = self._basic_funnel(properties={"$browser": "Safari"})

            # events
            with_property = person_factory(distinct_ids=["with_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="with_property", properties={"$browser": "Safari"})
            self._pay_event(distinct_id="with_property", properties={"$browser": "Safari"})

            # should not add a count
            without_property = person_factory(distinct_ids=["without_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="without_property")
            self._pay_event(distinct_id="without_property")

            # will add to first step
            half_property = person_factory(distinct_ids=["half_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="half_property", properties={"$browser": "Safari"})
            self._pay_event(distinct_id="half_property")

            calculate_actions_from_last_calculation()

            result = funnel.run()
            self.assertEqual(result[0]["count"], 2)
            self.assertEqual(result[1]["count"], 1)

        @test_with_materialized_columns(["$browser"])
        def test_funnel_prop_filters_per_entity(self):
            action_credit_card = Action.objects.create(team_id=self.team.pk, name="paid")
            ActionStep.objects.create(
                action=action_credit_card, event="$autocapture", tag_name="button", text="Pay $10"
            )
            action_play_movie = Action.objects.create(team_id=self.team.pk, name="watched movie")
            ActionStep.objects.create(action=action_play_movie, event="$autocapture", tag_name="a", href="/movie")
            filters = {
                "events": [
                    {
                        "id": "user signed up",
                        "type": "events",
                        "order": 0,
                        "properties": [
                            {"key": "$browser", "value": "Safari"},
                            {"key": "$browser", "operator": "is_not", "value": "Chrome"},
                        ],
                    },
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
            with_property = person_factory(
                distinct_ids=["with_property"], team_id=self.team.pk, properties={"$browser": "Safari"},
            )
            self._signup_event(distinct_id="with_property", properties={"$browser": "Safari"})
            self._pay_event(distinct_id="with_property", properties={"$browser": "Safari"})
            self._movie_event(distinct_id="with_property")

            # should not add a count
            without_property = person_factory(distinct_ids=["without_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="without_property")
            self._pay_event(distinct_id="without_property", properties={"$browser": "Safari"})

            # will add to first step
            half_property = person_factory(distinct_ids=["half_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="half_property")
            self._pay_event(distinct_id="half_property")
            self._movie_event(distinct_id="half_property")

            calculate_actions_from_last_calculation()

            result = funnel.run()

            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(result[1]["count"], 1)
            self.assertEqual(result[2]["count"], 0)

        @test_with_materialized_columns(person_properties=["email"])
        def test_funnel_person_prop(self):
            action_credit_card = Action.objects.create(team_id=self.team.pk, name="paid")
            ActionStep.objects.create(
                action=action_credit_card, event="$autocapture", tag_name="button", text="Pay $10"
            )
            action_play_movie = Action.objects.create(team_id=self.team.pk, name="watched movie")
            ActionStep.objects.create(action=action_play_movie, event="$autocapture", tag_name="a", href="/movie")
            filters = {
                "events": [
                    {
                        "id": "user signed up",
                        "type": "events",
                        "order": 0,
                        "properties": [{"key": "email", "value": "hello@posthog.com", "type": "person"},],
                    },
                ],
                "actions": [
                    {"id": action_credit_card.pk, "type": "actions", "order": 1,},
                    {"id": action_play_movie.pk, "type": "actions", "order": 2,},
                ],
                "funnel_window_days": 14,
            }
            funnel = self._basic_funnel(filters=filters)

            # events
            with_property = person_factory(
                distinct_ids=["with_property"], team_id=self.team.pk, properties={"email": "hello@posthog.com"},
            )
            self._signup_event(distinct_id="with_property")
            self._pay_event(distinct_id="with_property")
            self._movie_event(distinct_id="with_property")

            calculate_actions_from_last_calculation()

            result = funnel.run()
            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(result[1]["count"], 1)
            self.assertEqual(result[2]["count"], 1)

        @test_with_materialized_columns(["test_prop"])
        def test_funnel_multiple_actions(self):
            # we had an issue on clickhouse where multiple actions with different property filters would incorrectly grab only the last
            # properties.
            # This test prevents a regression
            person_factory(distinct_ids=["person1"], team_id=self.team.pk)
            event_factory(distinct_id="person1", event="event1", team=self.team)
            event_factory(distinct_id="person1", event="event2", properties={"test_prop": "a"}, team=self.team)

            action1 = Action.objects.create(team_id=self.team.pk, name="event2")
            ActionStep.objects.create(action=action1, event="event2", properties=[{"key": "test_prop", "value": "a"}])
            action1.calculate_events()
            action2 = Action.objects.create(team_id=self.team.pk, name="event2")
            ActionStep.objects.create(action=action2, event="event2", properties=[{"key": "test_prop", "value": "c"}])
            action2.calculate_events()

            result = Funnel(
                filter=Filter(
                    data={
                        "events": [{"id": "event1", "order": 0}],
                        "actions": [{"id": action1.pk, "order": 1,}, {"id": action2.pk, "order": 2,},],
                        "insight": INSIGHT_FUNNELS,
                        "funnel_window_days": 14,
                    }
                ),
                team=self.team,
            ).run()
            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(result[1]["count"], 1)
            self.assertEqual(result[2]["count"], 0)

        @test_with_materialized_columns(person_properties=["email"])
        def test_funnel_filter_test_accounts(self):
            person_factory(distinct_ids=["person1"], team_id=self.team.pk, properties={"email": "test@posthog.com"})
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
                    }
                ),
                team=self.team,
            ).run()
            self.assertEqual(result[0]["count"], 1)

        @test_with_materialized_columns(person_properties=["email"])
        def test_funnel_with_entity_person_property_filters(self):
            person_factory(distinct_ids=["person1"], team_id=self.team.pk, properties={"email": "test@posthog.com"})
            person_factory(distinct_ids=["person2"], team_id=self.team.pk, properties={"email": "another@example.com"})
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
                                    {"key": "email", "value": "is_set", "operator": "is_set", "type": "person"}
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

        @test_with_materialized_columns(person_properties=["email"], verify_no_jsonextract=False)
        def test_funnel_filter_by_action_with_person_properties(self):
            person_factory(distinct_ids=["person1"], team_id=self.team.pk, properties={"email": "test@posthog.com"})
            person_factory(distinct_ids=["person2"], team_id=self.team.pk, properties={"email": "another@example.com"})
            person_factory(distinct_ids=["person3"], team_id=self.team.pk)
            event_factory(distinct_id="person1", event="event1", team=self.team)
            event_factory(distinct_id="person2", event="event1", team=self.team)
            event_factory(distinct_id="person3", event="event1", team=self.team)

            action = Action.objects.create(team_id=self.team.pk, name="event1")
            ActionStep.objects.create(
                action=action,
                event="event1",
                properties=[{"key": "email", "value": "is_set", "operator": "is_set", "type": "person"}],
            )
            action.calculate_events()

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

    return TestGetFunnel


class TestFunnel(funnel_test_factory(Funnel, Event.objects.create, Person.objects.create)):  # type: ignore
    pass
