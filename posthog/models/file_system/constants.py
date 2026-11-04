from typing import TYPE_CHECKING

from django.db.models import Q

from posthog.ph_client import feature_enabled_or_false

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

WORKFLOW_FILE_SYSTEM_TYPES = frozenset({"hog_flow", "message_template"})


def workflow_project_files_enabled(team: "Team", user: "User") -> bool:
    return feature_enabled_or_false(
        "workflows-project-files",
        user.distinct_id or str(user.pk),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
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
