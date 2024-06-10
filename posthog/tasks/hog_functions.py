from typing import Optional

from celery import shared_task

from posthog.models.action.action import Action
from posthog.models.team.team import Team
from posthog.tasks.utils import CeleryQueue


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def refresh_affected_hog_functions(team: Optional[Team] = None, action: Optional[Action] = None) -> int:
    from posthog.models.hog_functions.hog_function import HogFunction

    if action:
        affected_hog_functions = (
            HogFunction.objects.select_related("team")
            .filter(team_id=action.team_id)
            .filter(filters__contains={"actions": [{"id": str(action.id)}]})
        )
    elif team:
        affected_hog_functions = (
            HogFunction.objects.select_related("team")
            .filter(team_id=team.id)
            .filter(filters__contains={"filter_test_accounts": True})
        )
    else:
        raise Exception("Either team or action must be provided")

    team_id: int = team.id if team else action.team_id

    all_related_actions = (
        Action.objects.select_related("team")
        .filter(team_id=team_id)
        .filter(
            id__in=[
                action_id for hog_function in affected_hog_functions for action_id in hog_function.filter_action_ids
            ]
        )
    )

    actions_by_id = {action.id: action for action in all_related_actions}

    for hog_function in affected_hog_functions:
        hog_function.compile_filters_bytecode(actions=actions_by_id)

    updates = HogFunction.objects.bulk_update(affected_hog_functions, ["filters"])

    return updates
