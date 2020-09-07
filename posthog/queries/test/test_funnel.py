from unittest.mock import patch

from posthog.api.test.base import BaseTest
from posthog.models import Action, ActionStep, Element, Event, Person
from posthog.models.filter import Filter
from posthog.queries.funnel import Funnel
from posthog.tasks.update_cache import update_cache_item


@patch("posthog.celery.update_cache_item_task.delay", update_cache_item)
class TestGetFunnel(BaseTest):
    TESTS_API = True

    def _signup_event(self, **kwargs):
        Event.objects.create(team=self.team, event="user signed up", **kwargs)

    def _pay_event(self, **kwargs):
        Event.objects.create(team=self.team, elements=[Element(tag_name="button", text="Pay $10")], **kwargs)

    def _movie_event(self, **kwargs):
        Event.objects.create(team=self.team, elements=[Element(tag_name="a", href="/movie")], **kwargs)

    def _single_step_funnel(self, properties=None, filters=None):
        if filters is None:
            filters = {
                "events": [{"id": "user signed up", "type": "events", "order": 0},],
            }

        if properties is not None:
            filters.update({"properties": properties})

        filter = Filter(data=filters)
        return Funnel(filter=filter, team=self.team)

    def _basic_funnel(self, properties=None, filters=None):
        action_credit_card = Action.objects.create(team=self.team, name="paid")
        ActionStep.objects.create(action=action_credit_card, tag_name="button", text="Pay $10")
        action_play_movie = Action.objects.create(team=self.team, name="watched movie")
        ActionStep.objects.create(action=action_play_movie, tag_name="a", href="/movie")

        if filters is None:
            filters = {
                "events": [{"id": "user signed up", "type": "events", "order": 0},],
                "actions": [
                    {"id": action_credit_card.pk, "type": "actions", "order": 1},
                    {"id": action_play_movie.pk, "type": "actions", "order": 2},
                ],
            }

        if properties is not None:
            filters.update({"properties": properties})

        filter = Filter(data=filters)
        return Funnel(filter=filter, team=self.team)

    def test_funnel_with_single_step(self):
        funnel = self._single_step_funnel()

        # event
        person1_stopped_after_signup = Person.objects.create(distinct_ids=["stopped_after_signup1"], team=self.team)
        self._signup_event(distinct_id="stopped_after_signup1")

        person2_stopped_after_signup = Person.objects.create(distinct_ids=["stopped_after_signup2"], team=self.team)
        self._signup_event(distinct_id="stopped_after_signup2")

        with self.assertNumQueries(1):
            result = funnel.run()
        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 2)
        # check ordering of people in first step
        self.assertEqual(
            result[0]["people"], [person1_stopped_after_signup.pk, person2_stopped_after_signup.pk],
        )

    def test_funnel_events(self):
        funnel = self._basic_funnel()

        # events
        person_stopped_after_signup = Person.objects.create(distinct_ids=["stopped_after_signup"], team=self.team)
        self._signup_event(distinct_id="stopped_after_signup")

        person_stopped_after_pay = Person.objects.create(distinct_ids=["stopped_after_pay"], team=self.team)
        self._signup_event(distinct_id="stopped_after_pay")
        self._pay_event(distinct_id="stopped_after_pay")

        person_stopped_after_movie = Person.objects.create(
            distinct_ids=["had_anonymous_id", "completed_movie"], team=self.team
        )
        self._signup_event(distinct_id="had_anonymous_id")
        self._pay_event(distinct_id="completed_movie")
        self._movie_event(distinct_id="completed_movie")

        person_that_just_did_movie = Person.objects.create(distinct_ids=["just_did_movie"], team=self.team)
        self._movie_event(distinct_id="just_did_movie")

        person_wrong_order = Person.objects.create(distinct_ids=["wrong_order"], team=self.team)
        self._pay_event(distinct_id="wrong_order")
        self._signup_event(distinct_id="wrong_order")
        self._movie_event(distinct_id="wrong_order")

        self._signup_event(distinct_id="a_user_that_got_deleted_or_doesnt_exist")

        result = funnel.run()
        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 4)
        # check ordering of people in first step
        self.assertEqual(
            result[0]["people"],
            [
                person_stopped_after_movie.pk,
                person_stopped_after_pay.pk,
                person_stopped_after_signup.pk,
                person_wrong_order.pk,
            ],
        )
        self.assertEqual(result[1]["name"], "paid")
        self.assertEqual(result[1]["count"], 2)
        self.assertEqual(result[2]["name"], "watched movie")
        self.assertEqual(result[2]["count"], 1)
        self.assertEqual(result[2]["people"], [person_stopped_after_movie.pk])

        # make sure it's O(n)
        person_wrong_order = Person.objects.create(distinct_ids=["badalgo"], team=self.team)
        self._signup_event(distinct_id="badalgo")
        with self.assertNumQueries(3):
            funnel.run()

        self._pay_event(distinct_id="badalgo")
        with self.assertNumQueries(3):
            funnel.run()

    def test_funnel_no_events(self):
        funnel = self._basic_funnel()

        with self.assertNumQueries(3):
            funnel.run()

    def test_funnel_skipped_step(self):
        funnel = self._basic_funnel()

        person_wrong_order = Person.objects.create(distinct_ids=["wrong_order"], team=self.team)
        self._signup_event(distinct_id="wrong_order")
        self._movie_event(distinct_id="wrong_order")

        result = funnel.run()
        self.assertEqual(result[1]["count"], 0)
        self.assertEqual(result[2]["count"], 0)

    def test_funnel_prop_filters(self):
        funnel = self._basic_funnel(properties={"$browser": "Safari"})

        # events
        with_property = Person.objects.create(distinct_ids=["with_property"], team=self.team)
        self._signup_event(distinct_id="with_property", properties={"$browser": "Safari"})
        self._pay_event(distinct_id="with_property", properties={"$browser": "Safari"})

        # should not add a count
        without_property = Person.objects.create(distinct_ids=["without_property"], team=self.team)
        self._signup_event(distinct_id="without_property")
        self._pay_event(distinct_id="without_property", properties={"$browser": "Safari"})

        # will add to first step
        half_property = Person.objects.create(distinct_ids=["half_property"], team=self.team)
        self._signup_event(distinct_id="half_property", properties={"$browser": "Safari"})
        self._pay_event(distinct_id="half_property")

        result = funnel.run()
        self.assertEqual(result[0]["count"], 2)
        self.assertEqual(result[1]["count"], 1)

    def test_funnel_prop_filters_per_entity(self):
        action_credit_card = Action.objects.create(team=self.team, name="paid")
        ActionStep.objects.create(action=action_credit_card, tag_name="button", text="Pay $10")
        action_play_movie = Action.objects.create(team=self.team, name="watched movie")
        ActionStep.objects.create(action=action_play_movie, tag_name="a", href="/movie")
        filters = {
            "events": [
                {
                    "id": "user signed up",
                    "type": "events",
                    "order": 0,
                    "properties": [{"key": "$browser", "value": "Safari"}],
                },
            ],
            "actions": [
                {
                    "id": action_credit_card.pk,
                    "type": "actions",
                    "order": 1,
                    "properties": [{"key": "$browser", "value": "Safari", "type": "person"}],
                },
                {
                    "id": action_play_movie.pk,
                    "type": "actions",
                    "order": 2,
                    "properties": [{"key": "$browser", "value": "Firefox"}],
                },
            ],
        }
        funnel = self._basic_funnel(filters=filters)

        # events
        with_property = Person.objects.create(
            distinct_ids=["with_property"], team=self.team, properties={"$browser": "Safari"},
        )
        self._signup_event(distinct_id="with_property", properties={"$browser": "Safari"})
        self._pay_event(distinct_id="with_property", properties={"$browser": "Safari"})
        self._movie_event(distinct_id="with_property")

        # should not add a count
        without_property = Person.objects.create(distinct_ids=["without_property"], team=self.team)
        self._signup_event(distinct_id="without_property")
        self._pay_event(distinct_id="without_property", properties={"$browser": "Safari"})

        # will add to first step
        half_property = Person.objects.create(distinct_ids=["half_property"], team=self.team)
        self._signup_event(distinct_id="half_property")
        self._pay_event(distinct_id="half_property")
        self._movie_event(distinct_id="half_property")

        result = funnel.run()

        self.assertEqual(result[0]["count"], 1)
        self.assertEqual(result[1]["count"], 1)
        self.assertEqual(result[2]["count"], 0)
