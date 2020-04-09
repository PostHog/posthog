# Create your tasks here

from celery import shared_task
from django.apps import apps
from django.conf import settings
import requests

@shared_task
def add(x, y):
    return x + y

@shared_task
def post_event_to_slack(event_id):
    # must import "Event" like this to avoid circular dependency with models.py (it imports tasks.py)
    event_model = apps.get_model(app_label='posthog', model_name='Event')
    event = event_model.objects.get(pk=event_id)
    team = event.team
    site_url = settings.SITE_URL

    if team.slack_incoming_webhook:
        user_plain = event.distinct_id
        user_markdown = "<{}/person/{}|{}>".format(site_url, event.distinct_id, event.distinct_id)

        actions = event.action_set.all()
        action_names = []

        for action in actions:
            if action.post_to_slack:
                action_names.append(action.name)

        if action_names:
            actions_string = ', '.join('"{}"'.format(name) for name in action_names)
            actions_string = "Action{} {}".format("" if len(action_names) == 1 else "s", actions_string)

            message = {
                "text": "{} triggered by user {}".format(actions_string, user_plain),
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "{} triggered by user {}".format(actions_string, user_markdown)
                        }
                    }
                ]
            }
            requests.post(team.slack_incoming_webhook, verify=False, json=message)
