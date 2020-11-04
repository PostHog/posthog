from posthog.models.event import Event
from ee.tasks.webhooks_ee import post_event_to_webhook_ee
from unittest.mock import call, patch
from uuid import uuid4
from dateutil.parser import isoparse

from django.utils.timezone import now
from posthog.api.test.base import BaseTest
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
import pytz


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    post_to_slack = kwargs.pop("post_to_slack")
    action = Action.objects.create(team=team, name=name, post_to_slack=post_to_slack)
    ActionStep.objects.create(action=action, event=name)
    return action


class TestWebhooksEE(BaseTest):
    @patch("requests.post")
    def test_post_event_to_webhook_ee(self, requests_post):

        self.team.slack_incoming_webhook = "http://slack.com/hook"
        self.team.save()
        _create_action(team=self.team, name="user paid", post_to_slack=True)
        _create_action(team=self.team, name="user not paid", post_to_slack=True)

        _now = now()

        if isinstance(_now, str):
            timestamp = isoparse(_now)
        else:
            timestamp = _now.astimezone(pytz.utc)

        event = {
            "event": "user paid",
            "properties": {},
            "distinct_id": "test",
            "timestamp": timestamp,
            "elements_list": {},
        }
        site_url = "http://testserver"
        post_event_to_webhook_ee(event, self.team.pk, site_url)

        self.assertEqual(requests_post.call_count, 1)

        events = Event.objects.filter(event="User paid")

        self.assertEqual(list(events), [])
