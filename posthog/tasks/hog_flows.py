from typing import Optional

from celery import shared_task

from posthog.models.action.action import Action
from posthog.plugins.plugin_server_api import reload_hog_flows_on_workers
from posthog.tasks.utils import CeleryQueue
from django.utils import timezone

from structlog import get_logger

logger = get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def refresh_affected_hog_flows(team_id: Optional[int] = None, action_id: Optional[int] = None) -> int:
    from posthog.models.hog_flow.hog_flow import HogFlow

    affected_hog_flows: list[HogFlow] = []

    if action_id:
        action = Action.objects.get(id=action_id)
        team_id = action.team_id
        # Find hog flows that reference this action in their trigger filters
        affected_hog_flows = list(
            HogFlow.objects.select_related("team")
            .filter(team_id=action.team_id, status="active")
            .filter(trigger__contains={"actions": [{"id": str(action_id)}]})
        )
    elif team_id:
        # Find hog flows that have test account filters enabled
        affected_hog_flows = list(
            HogFlow.objects.select_related("team")
            .filter(team_id=team_id, status="active")
            .filter(trigger__contains={"filter_test_accounts": True})
        )

    if team_id is None:
        raise Exception("Either team_id or action_id must be provided")

    if not affected_hog_flows:
        return 0

    # Update the updated_at timestamp to trigger a reload
    for hog_flow in affected_hog_flows:
        hog_flow.updated_at = timezone.now()

    updates = HogFlow.objects.bulk_update(affected_hog_flows, ["updated_at"])

    reload_hog_flows_on_workers(team_id=team_id, hog_flow_ids=[str(hog_flow.id) for hog_flow in affected_hog_flows])

    return updates
