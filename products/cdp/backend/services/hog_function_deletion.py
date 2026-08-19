from collections.abc import Iterable

from posthog.models.activity_logging.activity_log import Detail, log_activity

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.hog_functions.utils import humanize_hog_function_type


def bulk_soft_delete_hog_functions(functions: Iterable[HogFunction], *, deleted: bool = True) -> int:
    """Soft-delete (or restore) hog functions and write one activity log entry per function.

    Backend removal paths (data migrations, Celery tasks, management commands) must call this
    instead of a queryset `update(deleted=True)`. A bare `update()` skips the activity log, so a
    customer's transformation or destination disappears with no record of who removed it. The
    entries are system-triggered because no request user is present.

    Preload the team (`select_related("team")`) to avoid a query per row. Returns the count changed.
    """
    functions = list(functions)
    if not functions:
        return 0

    HogFunction.objects.filter(pk__in=[function.id for function in functions]).update(deleted=deleted)

    activity = "deleted" if deleted else "restored"
    for function in functions:
        log_activity(
            organization_id=function.team.organization_id,
            team_id=function.team_id,
            user=None,
            was_impersonated=False,
            item_id=str(function.id),
            scope="HogFunction",
            activity=activity,
            detail=Detail(name=function.name, type=humanize_hog_function_type(function.type)),
        )

    return len(functions)
