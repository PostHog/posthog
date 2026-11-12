from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from django.db.models import Q

from posthog.ph_client import feature_enabled_or_false

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

WORKFLOW_FILE_SYSTEM_TYPES = frozenset({"hog_flow", "message_template"})

_resolved_workflows_list_v2: ContextVar[dict[tuple[int, int], bool] | None] = ContextVar(
    "resolved_workflows_list_v2", default=None
)


def _evaluate_workflows_list_v2(team: "Team", user: "User", *, only_evaluate_locally: bool) -> bool:
    return feature_enabled_or_false(
        "workflows-list-v2",
        user.distinct_id or str(user.pk),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
        person_properties={"email": user.email},
        only_evaluate_locally=only_evaluate_locally,
        send_feature_flag_events=False,
    )


# The flag service can take seconds to answer. So the flag is evaluated locally everywhere, and only a
# request that files an object into a requested folder asks the service, through this scope, before it
# takes any lock. Saves inside the scope then read the answer instead of waiting on the service.
@contextmanager
def resolved_workflows_list_v2(team: "Team", users: Iterable["User"]) -> Iterator[None]:
    answers = dict(_resolved_workflows_list_v2.get() or {})
    for user in users:
        answers[(team.id, user.pk)] = _evaluate_workflows_list_v2(team, user, only_evaluate_locally=False)
    token = _resolved_workflows_list_v2.set(answers)
    try:
        yield
    finally:
        _resolved_workflows_list_v2.reset(token)


def workflows_list_v2_enabled(team: "Team", user: "User") -> bool:
    answers = _resolved_workflows_list_v2.get()
    if answers is not None and (team.id, user.pk) in answers:
        return answers[(team.id, user.pk)]
    return _evaluate_workflows_list_v2(team, user, only_evaluate_locally=True)


# The product surface a FileSystem row belongs to. Legacy rows predate this column and are
# stored as NULL; they are read as the default ("web"). New rows always store an explicit value.
DEFAULT_SURFACE = "web"

# Types of retired products. Their rows can stay in the database, but the type has no file system
# registration and no page to open. The tree hides them, and a delete removes only the row.
RETIRED_FILE_SYSTEM_TYPES: frozenset[str] = frozenset({"link"})


def surface_q(surface: str) -> Q:
    """Build the read filter for a surface. The default surface also matches legacy NULL rows."""
    if surface == DEFAULT_SURFACE:
        return Q(surface__isnull=True) | Q(surface=DEFAULT_SURFACE)
    return Q(surface=surface)
