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
    postgres_event = None
    try:
        team = Team.objects.select_related("organization").get(pk=team_id)
        postgres_event = Event.objects.create(
            event=event["event"],
            distinct_id=event["distinct_id"],
            properties=event["properties"],
            team=team,
            site_url=site_url,
            **({"timestamp": event["timestamp"]} if event["timestamp"] else {}),
            **({"elements": event["elements_list"]} if event["elements_list"] else {})
        )
        is_zapier_available = team.organization.is_feature_available("zapier")
        actionFilters = {"team_id": team_id}

        if not is_zapier_available:
            if not team.slack_incoming_webhook:
                return  # Exit this task if neither Zapier nor webhook URL are available
            else:
                actionFilters["post_to_slack"] = True  # We only need to fire for events that are posted to webhook URL

        actions = cast(Sequence[Action], Action.objects.filter(**actionFilters).all())

        if not site_url:
            site_url = settings.SITE_URL

        for action in actions:
            qs = Event.objects.filter(pk=postgres_event.pk).query_db_by_action(action)
            if not qs:
                continue
            # REST hooks
            if is_zapier_available:
                action.on_perform(postgres_event)
            # webhooks
            if team.slack_incoming_webhook:
                message_text, message_markdown = get_formatted_message(action, postgres_event, site_url,)
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
        self.retry(countdown=(2 ** self.request.retries) / 2)
    finally:
        # Ensure that the temporary Postgres event is deleted
        if postgres_event is not None:
            postgres_event.delete()
