from typing import Optional

from celery import shared_task
from django.conf import settings

from posthog.cdp.filters import compile_filters_bytecode
from posthog.event_usage import report_team_action
from posthog.models.action.action import Action
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers
from posthog.tasks.email import send_hog_function_disabled
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


# Called from the plugin-server hog-watcher.ts
@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def hog_function_state_transition(hog_function_id: str, state: int) -> None:
    from posthog.models.hog_functions.hog_function import HogFunction

    hog_function = HogFunction.objects.get(id=hog_function_id)

    if not hog_function:
        return

    report_team_action(
        hog_function.team,
        "hog function state changed",
        {
            "hog_function_id": hog_function_id,
            "hog_function_url": f"{settings.SITE_URL}/project/{hog_function.team.id}/pipeline/destinations/hog-{hog_function_id}",
        },
    )

    send_hog_function_disabled.delay(hog_function_id=hog_function_id, state=state)

    # Do the email sending logic
