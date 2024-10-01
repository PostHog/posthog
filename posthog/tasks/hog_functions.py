from typing import Optional

from celery import shared_task

from posthog.cdp.filters import compile_filters_bytecode
from posthog.models.action.action import Action
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers
from posthog.tasks.utils import CeleryQueue


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def refresh_affected_hog_functions(team_id: Optional[int] = None, action_id: Optional[int] = None) -> int:
    from posthog.models.hog_functions.hog_function import HogFunction

    affected_hog_functions: list[HogFunction] = []

    if action_id:
        action = Action.objects.get(id=action_id)
        team_id = action.team_id
        affected_hog_functions = list(
            HogFunction.objects.select_related("team")
            .filter(team_id=action.team_id)
            .filter(filters__contains={"actions": [{"id": str(action_id)}]})
        )
    elif team_id:
        affected_hog_functions = list(
            HogFunction.objects.select_related("team")
            .filter(team_id=team_id)
            .filter(filters__contains={"filter_test_accounts": True})
        )

    if team_id is None:
        raise Exception("Either team_id or action_id must be provided")

    if not affected_hog_functions:
        return 0

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
        hog_function.filters = compile_filters_bytecode(hog_function.filters, hog_function.team, actions_by_id)

    updates = HogFunction.objects.bulk_update(affected_hog_functions, ["filters"])

    reload_hog_functions_on_workers(
        team_id=team_id, hog_function_ids=[str(hog_function.id) for hog_function in affected_hog_functions]
    )

    return updates
