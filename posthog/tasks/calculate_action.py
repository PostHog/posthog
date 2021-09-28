import logging
import time
from typing import Sequence, cast

from celery import shared_task

from posthog.models import Action
from posthog.utils import is_clickhouse_enabled

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def calculate_action(action_id: int) -> None:
    start_time = time.time()
    action = Action.objects.get(pk=action_id)
    action.calculate_events()
    total_time = time.time() - start_time
    logger.info(f"Calculating action {action.pk} took {total_time:.2f} seconds")


def calculate_actions_from_last_calculation() -> None:
    if is_clickhouse_enabled():  # In EE, actions are not precalculated
        return
    start_time_overall = time.time()
    for action in cast(Sequence[Action], Action.objects.filter(is_calculating=False, deleted=False)):
        start_time = time.time()
        action.calculate_events(start=action.last_calculated_at)
        total_time = time.time() - start_time
        logger.info(f"Calculating action {action.pk} took {total_time:.2f} seconds")
    total_time_overall = time.time() - start_time_overall
    logger.info(f"Calculated new event-action pairs in {total_time_overall:.2f} s")
