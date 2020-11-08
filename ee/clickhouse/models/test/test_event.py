from unittest.mock import call, patch
from uuid import uuid4

from django.utils.timezone import now

from ee.clickhouse.models.event import create_event
from posthog.api.test.base import BaseTest
from posthog.models.action import Action
from posthog.models.action_step import ActionStep


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    post_to_slack = kwargs.pop("post_to_slack")
    action = Action.objects.create(team=team, name=name, post_to_slack=post_to_slack)
    ActionStep.objects.create(action=action, event=name)
    return action


class TestSendToSlackClickhouse(BaseTest):
    @patch("celery.current_app.send_task")
    def test_send_to_slack(self, patch_post_to_slack):
        self.team.slack_incoming_webhook = "http://slack.com/hook"
        _create_action(team=self.team, name="user paid", post_to_slack=True)

        _now = now()
        create_event(
            event_uuid=uuid4(),
            team=self.team,
            distinct_id="test",
            event="user paid",
            site_url="http://testserver",
            timestamp=_now,
        )
        self.assertEqual(patch_post_to_slack.call_count, 1)
        patch_post_to_slack.assert_has_calls(
            [
                call(
                    "ee.tasks.webhooks_ee.post_event_to_webhook_ee",
                    (
                        {
                            "event": "user paid",
                            "properties": {},
                            "distinct_id": "test",
                            "timestamp": _now,
                            "elements_list": None,
                        },
                        self.team.pk,
                        "http://testserver",
                    ),
                )
            ]
        )
