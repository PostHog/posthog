from unittest.mock import patch

import pytz
from django.utils.timezone import now

from ee.tasks.webhooks_ee import post_event_to_webhook_ee
from posthog.api.test.base import BaseTest
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.event import Event


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    post_to_slack = kwargs.pop("post_to_slack")
    action = Action.objects.create(team=team, name=name, post_to_slack=post_to_slack)
    ActionStep.objects.create(action=action, event=name)
    return action


class TestWebhooksEE(BaseTest):
    @patch("requests.post")
    @patch("celery.current_app.send_task")
    def test_post_event_to_webhook_ee(self, requests_post, _):

        self.team.slack_incoming_webhook = "http://slack.com/hook"
        self.team.save()
        _create_action(team=self.team, name="user paid", post_to_slack=True)
        _create_action(team=self.team, name="user not paid", post_to_slack=True)

        _now = now()

        event = {
            "event": "user paid",
            "properties": {},
            "distinct_id": "test",
            "timestamp": _now,
            "elements_list": {},
        }
        site_url = "http://testserver"
        post_event_to_webhook_ee(event, self.team.pk, site_url)

        self.assertEqual(requests_post.call_count, 1)

        events = Event.objects.filter(event="User paid")

        self.assertEqual(list(events), [])
