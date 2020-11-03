import re
from typing import Any, Dict, List

import requests
from celery import Task
from django.conf import settings
from django.db.models.expressions import Exists, OuterRef
from django.db.models.query_utils import Q
from django.forms.models import model_to_dict

from posthog.celery import app
from posthog.constants import AUTOCAPTURE_EVENT
from posthog.models import Action, Event, Team
from posthog.models.action_step import ActionStep
from posthog.models.filter import Filter
from posthog.tasks.webhooks import determine_webhook_type, get_formatted_message


@app.task(ignore_result=True, bind=True, max_retries=3)
def post_event_to_webhook_ee(self: Task, event: Dict[str, Any], team_id: int, site_url: str) -> None:
    try:

        team = Team.objects.get(pk=team_id)
        _event = Event(
            id=0,
            event=event["event"],
            distinct_id=event["distinct_id"],
            properties=event["properties"],
            team=team,
            site_url=site_url,
            **({"timestamp": event["timestamp"]} if event["timestamp"] else {}),
            **({"elements": event["elements_list"]} if event["elements_list"] else {})
        )

        if not site_url:
            site_url = settings.SITE_URL

        if team.slack_incoming_webhook:
            for action in _event.actions:
                message_text, message_markdown = get_formatted_message(action, _event, site_url,)
                if determine_webhook_type(team) == "slack":
                    message = {
                        "text": message_text,
                        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": message_markdown},},],
                    }
                else:
                    message = {
                        "text": message_markdown,
                    }
                requests.post(team.slack_incoming_webhook, verify=False, json=message)
    except:
        self.retry(countdown=2 ** self.request.retries)