import logging
import time

from celery import current_app, shared_task

from posthog.celery import app
from posthog.models import Action, Event

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def calculate_action(action_id: int) -> None:
    start_time = time.time()
    action = Action.objects.get(pk=action_id)
    action.calculate_events()
    logger.info("Calculating action {} took {:.2f} seconds".format(action.pk, (time.time() - start_time)))


@app.task(ignore_result=True)
def calculate_actions_for_event(event_id: str, site_url: str) -> None:
    event = Event.objects.get(pk=event_id)
    event_should_trigger_webhook = False

    for action in event.actions:
        start_time = time.time()
        action.calculate_events(start=action.last_calculated_at)
        logger.info("Calculating action {} took {:.2f} seconds".format(action.pk, (time.time() - start_time)))
        if action.post_to_slack:
            event_should_trigger_webhook = True

    if event_should_trigger_webhook:
        current_app.send_task("posthog.tasks.webhooks.post_event_to_webhook", args=[event_id, site_url])
