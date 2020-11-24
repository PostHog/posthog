from datetime import datetime
from json import dumps as jdumps
from unittest.mock import call, patch

from freezegun import freeze_time

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.models import (
    Action,
    ActionStep,
    Cohort,
    Element,
    Entity,
    Event,
    Filter,
    Person,
    Team,
)

from .base import BaseTest, TransactionBaseTest


@patch("posthog.tasks.calculate_action.calculate_action.delay")
class TestCreateAction(BaseTest):
    TESTS_API = True

    def test_create_and_update_action(self, patch_delay):
        Event.objects.create(
            team=self.team,
            event="$autocapture",
            elements=[Element(tag_name="button", text="sign up NOW"), Element(tag_name="div"),],
        )
        response = self.client.post(
            "/api/action/",
            data={
                "name": "user signed up",
                "steps": [{"text": "sign up", "selector": "div > button", "url": "/signup", "isNew": "asdf",}],
            },
            content_type="application/json",
            HTTP_ORIGIN="http://testserver",
        ).json()
        action = Action.objects.get()
        self.assertEqual(action.name, "user signed up")
        self.assertEqual(action.team, self.team)
        self.assertEqual(action.steps.get().selector, "div > button")
        self.assertEqual(response["steps"][0]["text"], "sign up")

        # test no actions with same name
        user2 = self._create_user("tim2")
        self.client.force_login(user2)

        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            "/api/action",
            data={"name": "user signed up"},
            content_type="application/json",
            HTTP_ORIGIN="http://testserver",
        ).json()
        self.assertEqual(response["detail"], "action-exists")

        # test update
        event2 = Event.objects.create(
            team=self.team,
            event="$autocapture",
            properties={"$browser": "Chrome"},
            elements=[Element(tag_name="button", text="sign up NOW"), Element(tag_name="div"),],
        )
        response = self.client.patch(
            "/api/action/%s/" % action.pk,
            data={
                "name": "user signed up 2",
                "steps": [
                    {
                        "id": action.steps.get().pk,
                        "isNew": "asdf",
                        "text": "sign up NOW",
                        "selector": "div > button",
                        "properties": [{"key": "$browser", "value": "Chrome"}],
                        "url": None,
                    },
                    {"href": "/a-new-link"},
                ],
                "created_by": {
                    "id": 1,
                    "distinct_id": "BLKJzxHq4z2d8P1icfpg5wo4eIHaSrMtnotkwdtD8Ok",
                    "first_name": "person",
                    "email": "person@email.com",
                },
            },
            content_type="application/json",
            HTTP_ORIGIN="http://testserver",
        ).json()
        action = Action.objects.get()
        action.calculate_events()
        steps = action.steps.all().order_by("id")
        self.assertEqual(action.name, "user signed up 2")
        self.assertEqual(steps[0].text, "sign up NOW")
        self.assertEqual(steps[1].href, "/a-new-link")
        self.assertEqual(action.events.get(), event2)
        self.assertEqual(action.events.count(), 1)

        # test queries
        with self.assertNumQueries(6):
            response = self.client.get("/api/action/")

        # test remove steps
        response = self.client.patch(
            "/api/action/%s/" % action.pk,
            data={"name": "user signed up 2", "steps": [],},
            content_type="application/json",
            HTTP_ORIGIN="http://testserver",
        ).json()
        self.assertEqual(ActionStep.objects.count(), 0)

    # When we send a user to their own site, we give them a token.
    # Make sure you can only create actions if that token is set,
    # otherwise evil sites could create actions with a users' session.
    # NOTE: Origin header is only set on cross domain request
    def test_create_from_other_domain(self, patch_delay):
        # FIXME: BaseTest is using Django client to performe calls to a DRF endpoint.
        # Django HttpResponse does not have an attribute `data`. Better use rest_framework.test.APIClient.
        response = self.client.post(
            "/api/action/",
            data={"name": "user signed up",},
            content_type="application/json",
            HTTP_ORIGIN="https://evilwebsite.com",
        )
        self.assertEqual(response.status_code, 403)

        self.user.temporary_token = "token123"
        self.user.save()

        response = self.client.post(
            "/api/action/?temporary_token=token123",
            data={"name": "user signed up",},
            content_type="application/json",
            HTTP_ORIGIN="https://somewebsite.com",
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/api/action/?temporary_token=token123",
            data={"name": "user signed up and post to slack", "post_to_slack": True,},
            content_type="application/json",
            HTTP_ORIGIN="https://somewebsite.com",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["post_to_slack"], True)

        list_response = self.client.get(
            "/api/action/", content_type="application/json", HTTP_ORIGIN="https://evilwebsite.com",
        )
        self.assertEqual(list_response.status_code, 403)

        detail_response = self.client.get(
            f"/api/action/{response.json()['id']}/",
            content_type="application/json",
            HTTP_ORIGIN="https://evilwebsite.com",
        )
        self.assertEqual(detail_response.status_code, 403)

        self.client.logout()
        list_response = self.client.get(
            "/api/action/",
            data={"temporary_token": "token123",},
            content_type="application/json",
            HTTP_ORIGIN="https://somewebsite.com",
        )
        self.assertEqual(list_response.status_code, 200)

        response = self.client.post(
            "/api/action/?temporary_token=token123",
            data={"name": "user signed up 22",},
            content_type="application/json",
            HTTP_ORIGIN="https://somewebsite.com",
        )
        self.assertEqual(response.status_code, 200, response.json())

    # This case happens when someone is running behind a proxy, but hasn't set `IS_BEHIND_PROXY`
    def test_http_to_https(self, patch_delay):
        response = self.client.post(
            "/api/action/",
            data={"name": "user signed up again",},
            content_type="application/json",
            HTTP_ORIGIN="https://testserver/",
        )
        self.assertEqual(response.status_code, 200, response.json())
