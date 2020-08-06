import time
from typing import Optional
from unittest.mock import patch

from django.core.cache import cache

from posthog.models import Action, ActionStep, Element, Event, Funnel, Person
from posthog.tasks.update_cache import update_cache_item
from posthog.utils import generate_cache_key

from .base import BaseTest


@patch("posthog.celery.update_cache_item_task.delay", update_cache_item)
class TestCreateFunnel(BaseTest):
    TESTS_API = True

    def test_create_funnel(self):
        action_sign_up = Action.objects.create(team=self.team, name="signed up")
        ActionStep.objects.create(action=action_sign_up, tag_name="button", text="Sign up!")
        action_credit_card = Action.objects.create(team=self.team, name="paid")
        ActionStep.objects.create(action=action_credit_card, tag_name="button", text="Pay $10")
        action_play_movie = Action.objects.create(team=self.team, name="watched movie")
        ActionStep.objects.create(action=action_play_movie, tag_name="a", href="/movie")
        action_logout = Action.objects.create(team=self.team, name="user logged out")

        [action.calculate_events() for action in Action.objects.all()]

        response = self.client.post(
            "/api/funnel/",
            data={
                "name": "Whatever",
                "filters": {
                    "events": [{"id": "user signed up", "type": "events", "order": 0},],
                    "actions": [{"id": action_sign_up.pk, "type": "actions", "order": 1},],
                },
            },
            content_type="application/json",
        ).json()
        funnels = Funnel.objects.get()
        self.assertEqual(funnels.filters["actions"][0]["id"], action_sign_up.pk)
        self.assertEqual(funnels.filters["events"][0]["id"], "user signed up")
        self.assertEqual(funnels.get_steps()[0]["order"], 0)
        self.assertEqual(funnels.get_steps()[1]["order"], 1)

    def test_create_funnel_element_filters(self):
        self.client.post(
            "/api/funnel/",
            data={
                "name": "Whatever",
                "filters": {
                    "events": [
                        {
                            "id": "$autocapture",
                            "name": "$autocapture",
                            "type": "events",
                            "order": 0,
                            "properties": [{"key": "text", "type": "element", "value": "Sign up"}],
                        }
                    ]
                },
            },
            content_type="application/json",
        ).json()
        funnels = Funnel.objects.get()
        self.assertEqual(funnels.filters["events"][0]["id"], "$autocapture")
        self.assertEqual(funnels.get_steps()[0]["order"], 0)

    def test_delete_funnel(self):
        funnel = Funnel.objects.create(team=self.team)
        response = self.client.patch(
            "/api/funnel/%s/" % funnel.pk, data={"deleted": True, "steps": []}, content_type="application/json",
        ).json()
        response = self.client.get("/api/funnel/").json()
        self.assertEqual(len(response["results"]), 0)

    # Autosaving in frontend means funnel without steps get created
    def test_create_and_update_funnel_no_steps(self):
        response = self.client.post("/api/funnel/", data={"name": "Whatever"}, content_type="application/json").json()
        self.assertEqual(Funnel.objects.get().name, "Whatever")

        response = self.client.patch(
            "/api/funnel/%s/" % response["id"], data={"name": "Whatever2"}, content_type="application/json",
        ).json()
        self.assertEqual(Funnel.objects.get().name, "Whatever2")


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

        funnel = Funnel.objects.create(team=self.team, name="funnel", filters=filters)
        return funnel

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

        funnel = Funnel.objects.create(team=self.team, name="funnel", filters=filters)
        return funnel

    def _poll_funnel(self, url: str, refresh=False) -> dict:
        loading = True
        timeout = time.time() + 10  # stop in 10 seconds
        response = {}

        if refresh:
            response = self.client.get(url + "?refresh=true").json()
            loading = response.get("loading", None)

        while loading:
            test = 0
            response = self.client.get(url).json()
            loading = response.get("loading", None)
            if time.time() > timeout:
                break
            test = test - 1
        return response

    def test_funnel_with_single_step(self):
        funnel = self._single_step_funnel()

        # event
        person1_stopped_after_signup = Person.objects.create(distinct_ids=["stopped_after_signup1"], team=self.team)
        self._signup_event(distinct_id="stopped_after_signup1")

        person2_stopped_after_signup = Person.objects.create(distinct_ids=["stopped_after_signup2"], team=self.team)
        self._signup_event(distinct_id="stopped_after_signup2")

        with self.assertNumQueries(10):
            response = self._poll_funnel(url="/api/funnel/{}/".format(funnel.pk))

        self.assertEqual(response["steps"][0]["name"], "user signed up")
        self.assertEqual(response["steps"][0]["count"], 2)
        # check ordering of people in first step
        self.assertEqual(
            response["steps"][0]["people"], [person1_stopped_after_signup.pk, person2_stopped_after_signup.pk],
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

        with self.assertNumQueries(12):
            response = self._poll_funnel("/api/funnel/{}/".format(funnel.pk))
        self.assertEqual(response["steps"][0]["name"], "user signed up")
        self.assertEqual(response["steps"][0]["count"], 4)
        # check ordering of people in first step
        self.assertEqual(
            response["steps"][0]["people"],
            [
                person_stopped_after_movie.pk,
                person_stopped_after_pay.pk,
                person_stopped_after_signup.pk,
                person_wrong_order.pk,
            ],
        )
        self.assertEqual(response["steps"][1]["name"], "paid")
        self.assertEqual(response["steps"][1]["count"], 2)
        self.assertEqual(response["steps"][2]["name"], "watched movie")
        self.assertEqual(response["steps"][2]["count"], 1)
        self.assertEqual(response["steps"][2]["people"], [person_stopped_after_movie.pk])

        # make sure it's O(n)
        person_wrong_order = Person.objects.create(distinct_ids=["badalgo"], team=self.team)
        self._signup_event(distinct_id="badalgo")
        with self.assertNumQueries(12):
            response = self._poll_funnel(url="/api/funnel/{}/".format(funnel.pk), refresh=True)

        self._pay_event(distinct_id="badalgo")
        with self.assertNumQueries(12):
            response = self._poll_funnel(url="/api/funnel/{}/".format(funnel.pk), refresh=True)

    def test_funnel_no_events(self):
        funnel = self._basic_funnel()

        with self.assertNumQueries(12):
            response = self._poll_funnel("/api/funnel/{}/".format(funnel.pk))

    def test_funnel_skipped_step(self):
        funnel = self._basic_funnel()

        person_wrong_order = Person.objects.create(distinct_ids=["wrong_order"], team=self.team)
        self._signup_event(distinct_id="wrong_order")
        self._movie_event(distinct_id="wrong_order")

        response = self._poll_funnel("/api/funnel/{}/".format(funnel.pk))
        self.assertEqual(response["steps"][1]["count"], 0)
        self.assertEqual(response["steps"][2]["count"], 0)

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

        response = self._poll_funnel("/api/funnel/{}/".format(funnel.pk))
        self.assertEqual(response["steps"][0]["count"], 2)
        self.assertEqual(response["steps"][1]["count"], 1)

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

        response = self._poll_funnel("/api/funnel/{}/".format(funnel.pk))
        self.assertEqual(response["steps"][0]["count"], 1)
        self.assertEqual(response["steps"][1]["count"], 1)
        self.assertEqual(response["steps"][2]["count"], 0)

    def test_cached_funnel(self):
        action_sign_up = Action.objects.create(team=self.team, name="signed up")
        ActionStep.objects.create(action=action_sign_up, tag_name="button", text="Sign up!")
        action_credit_card = Action.objects.create(team=self.team, name="paid")
        ActionStep.objects.create(action=action_credit_card, tag_name="button", text="Pay $10")
        action_play_movie = Action.objects.create(team=self.team, name="watched movie")
        ActionStep.objects.create(action=action_play_movie, tag_name="a", href="/movie")
        Action.objects.create(team=self.team, name="user logged out")

        [action.calculate_events() for action in Action.objects.all()]

        self.client.post(
            "/api/funnel/",
            data={
                "name": "Whatever",
                "filters": {
                    "events": [{"id": "user signed up", "type": "events", "order": 0},],
                    "actions": [{"id": action_sign_up.pk, "type": "actions", "order": 1},],
                },
            },
            content_type="application/json",
        ).json()
        funnel = Funnel.objects.get()

        funnel_key = generate_cache_key("funnel_{}_{}".format(funnel.pk, self.team.pk))

        # no refresh after getting
        self.client.get("/api/funnel/{}/".format(funnel.pk)).json()
        original_name = cache.get(funnel_key)["result"]["name"]

        self.client.patch(
            "/api/funnel/{}/".format(funnel.pk), data={"name": "Whatever2"}, content_type="application/json"
        ).json()

        self.client.get("/api/funnel/{}/".format(funnel.pk)).json()
        refreshed_name = cache.get(funnel_key)["result"]["name"]
        self.assertEqual("Whatever", refreshed_name)

        self.client.get("/api/funnel/{}/?refresh=true".format(funnel.pk)).json()
        refreshed_name = cache.get(funnel_key)["result"]["name"]
        self.assertEqual("Whatever2", refreshed_name)
