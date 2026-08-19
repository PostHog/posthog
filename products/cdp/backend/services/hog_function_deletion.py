from collections import defaultdict
from collections.abc import Iterable

from django.db import transaction

from posthog.models.activity_logging.activity_log import Detail, LogActivityEntry, bulk_log_activity
from posthog.models.team.team import Team
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers

from products.cdp.backend.models.hog_functions.hog_function import TYPES_THAT_RELOAD_PLUGIN_SERVER, HogFunction
from products.cdp.backend.models.hog_functions.utils import humanize_hog_function_type


def bulk_soft_delete_hog_functions(functions: Iterable[HogFunction], *, deleted: bool = True) -> int:
    """Soft-delete (or restore) hog functions and write one activity log entry per function.

    Backend removal paths (data migrations, Celery tasks, management commands) must call this
    instead of a queryset `update(deleted=True)`. A bare `update()` skips two things: the activity
    log, so a customer's transformation or destination disappears with no record of who removed it;
    and the `post_save` reload, so workers keep executing a deleted function until their cache
    refreshes. This helper writes system-triggered audit rows (no request user) and reloads the
    affected workers after the transaction commits.

    Returns the count of functions changed.
    """
    functions = list(functions)
    if not functions:
        return 0

    # nosemgrep: idor-lookup-without-team (PKs come from already team-scoped instances)
    HogFunction.objects.filter(pk__in=[function.id for function in functions]).update(deleted=deleted)

    # One team-to-organization lookup for the whole batch, rather than one query per function.
    org_by_team = dict(
        Team.objects.filter(id__in={function.team_id for function in functions}).values_list("id", "organization_id")
    )

    activity = "deleted" if deleted else "restored"
    # notify=False: a sweep must not put one internal event per row onto the internal-events topic.
    bulk_log_activity(
        [
            LogActivityEntry(
                organization_id=org_by_team.get(function.team_id),
                team_id=function.team_id,
                user=None,
                was_impersonated=False,
                item_id=str(function.id),
                scope="HogFunction",
                activity=activity,
                detail=Detail(name=function.name, type=humanize_hog_function_type(function.type)),
            )
            for function in functions
        ],
        notify=False,
    )

    # A queryset update() fires no post_save, so reload the workers ourselves for executable types.
    reload_ids_by_team: dict[int, list[str]] = defaultdict(list)
    for function in functions:
        if function.type is None or function.type in TYPES_THAT_RELOAD_PLUGIN_SERVER:
            reload_ids_by_team[function.team_id].append(str(function.id))

    for team_id, hog_function_ids in reload_ids_by_team.items():
        transaction.on_commit(
            lambda team_id=team_id, hog_function_ids=hog_function_ids: reload_hog_functions_on_workers(
                team_id=team_id, hog_function_ids=sorted(hog_function_ids)
            ),
            robust=True,
        )

    return len(functions)
