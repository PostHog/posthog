import re
from typing import Any, Dict, Sequence, cast

import requests
from celery import Task
from django.conf import settings

from ee.clickhouse.models.element import chain_to_elements
from posthog.celery import app
from posthog.models import Action, Event, Team
from posthog.tasks.webhooks import determine_webhook_type, get_formatted_message


@app.task(ignore_result=True, bind=True, max_retries=3)
def post_event_to_webhook_ee(self: Task, event: Dict[str, Any], team_id: int, site_url: str) -> None:
    team = Team.objects.select_related("organization").get(pk=team_id)
    is_zapier_available = team.organization.is_feature_available("zapier")

    elements_list = chain_to_elements(event.get("elements_chain", ""))
    ephemeral_postgres_event = Event.objects.create(
        event=event["event"],
        distinct_id=event["distinct_id"],
        properties=event["properties"],
        team=team,
        site_url=site_url,
        **({"timestamp": event["timestamp"]} if event["timestamp"] else {}),
        **({"elements": elements_list})
    )

    if not site_url:
        site_url = settings.SITE_URL

    actionFilters = {"team_id": team_id}
    if not is_zapier_available:
        if not team.slack_incoming_webhook:
            return  # Exit this task if neither Zapier nor webhook URL are available
        else:
            actionFilters["post_to_slack"] = True  # We only need to fire for actions that are posted to webhook URL

    for action in cast(Sequence[Action], Action.objects.filter(**actionFilters).all()):
        qs = Event.objects.filter(pk=ephemeral_postgres_event.pk).query_db_by_action(action)
        if not qs:
            continue
        # REST hooks
        if is_zapier_available:
            action.on_perform(ephemeral_postgres_event)
        # webhooks
        if not team.slack_incoming_webhook:
            continue
        message_text, message_markdown = get_formatted_message(action, ephemeral_postgres_event, site_url,)
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

    ephemeral_postgres_event.delete()
