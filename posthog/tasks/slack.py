from celery import shared_task
from django.apps import apps
from django.conf import settings
import requests

@shared_task
def post_event_to_slack(event_id: int, site_url: str) -> None:
    # must import "Event" like this to avoid circular dependency with models.py (it imports tasks.py)
    event_model = apps.get_model(app_label='posthog', model_name='Event')
    event = event_model.objects.get(pk=event_id)
    team = event.team

    if not site_url:
        site_url = settings.SITE_URL

    if team.slack_incoming_webhook:
        try:
            user_name = event.person.properties.get('email', event.distinct_id)
        except:
            user_name = event.distinct_id

        webhook_type = 'teams'
        if "slack.com" in team.slack_incoming_webhook:
            webhook_type = 'slack'

        if webhook_type == 'slack':
            user_markdown = "<{}/person/{}|{}>".format(site_url, event.distinct_id, user_name)
        else:
            user_markdown = "[{}]({}/person/{})".format(user_name, site_url, event.distinct_id)

        actions = [action for action in event.action_set.all() if action.post_to_slack]

        if actions:
            if webhook_type == 'slack':
                action_links = ', '.join('"<{}/action/{}|{}>"'.format(site_url, action.id, action.name) for action in actions)
            else:
                action_links = ', '.join('"[{}]({}/action/{})"'.format(action.name, site_url, action.id) for action in actions)

            action_names = ', '.join('"{}"'.format(action.name) for action in actions)

            actions_markdown = "Action{} {}".format("" if len(actions) == 1 else "s", action_links)
            actions_plain = "Action{} {}".format("" if len(actions) == 1 else "s", action_names)

            if webhook_type == 'slack':
                message = {
                    "text": "{} triggered by user {}".format(actions_plain, user_name),
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "{} triggered by user {}".format(actions_markdown, user_markdown)
                            }
                        }
                    ]
                }
            else:
                message = {
                    "text": "{} triggered by user {}".format(actions_markdown, user_markdown),
                }

            requests.post(team.slack_incoming_webhook, verify=False, json=message)
