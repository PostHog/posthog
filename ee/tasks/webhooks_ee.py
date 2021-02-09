import re
from typing import Any, Dict, Sequence, cast

import requests
from celery import Task
from django.conf import settings

from posthog.celery import app
from posthog.models import Action, Event, Team
from posthog.tasks.webhooks import determine_webhook_type, get_formatted_message


@app.task(ignore_result=True, bind=True, max_retries=3)
def post_event_to_webhook_ee(self: Task, event: Dict[str, Any], team_id: int, site_url: str) -> None:
    team = Team.objects.get(pk=team_id)
    _event = Event.objects.create(
        event=event["event"],
        distinct_id=event["distinct_id"],
        properties=event["properties"],
        team=team,
        site_url=site_url,
        **({"timestamp": event["timestamp"]} if event["timestamp"] else {}),
        **({"elements": event["elements_list"]} if event["elements_list"] else {})
    )

    actions = cast(Sequence[Action], Action.objects.filter(team_id=team_id, post_to_slack=True).all())

    if not site_url:
        site_url = settings.SITE_URL

    for action in actions:
        qs = Event.objects.filter(pk=_event.pk).query_db_by_action(action)
        if not qs:
            continue
        # REST hooks
        action.on_perform(_event)
        # webhooks
        if not team.slack_incoming_webhook:
            continue
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

    _event.delete()
