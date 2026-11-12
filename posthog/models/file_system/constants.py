from typing import TYPE_CHECKING

from django.db.models import Q

from posthog.ph_client import feature_enabled_or_false
from posthog.utils import flag_identity

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

WORKFLOW_FILE_SYSTEM_TYPES = frozenset({"hog_flow", "message_template"})


# File reads evaluate the flag locally only, so that file navigation never waits on the flag service.
# Only a create or restore into a requested folder may ask the service, so that its placement survives
# when local evaluation cannot decide.
def workflows_list_v2_enabled(team: "Team", user: "User", *, allow_remote_evaluation: bool = False) -> bool:
    # The browser shows the list from this flag, so the server must evaluate it with the identity the app sends.
    # Otherwise a project-targeted rollout shows the new list with counts and files from the old one.
    identity = flag_identity(user, team, team.organization)
    if identity is None:
        return False
    return feature_enabled_or_false(
        "workflows-list-v2",
        identity.distinct_id,
        groups=identity.groups,
        person_properties=identity.person_properties,
        group_properties=identity.group_properties,
        only_evaluate_locally=not allow_remote_evaluation,
        send_feature_flag_events=False,
    )


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
