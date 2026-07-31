from typing import Literal

import posthoganalytics

from posthog.event_usage import EventSource, groups
from posthog.models import Team, User

# Shown in place of a chart whose reference no longer resolves to any query.
UNRESOLVED_VISUALIZATION_MESSAGE = "This chart couldn't be loaded. Ask Max to rebuild it."

UNRESOLVED_VISUALIZATION_EVENT = "ai notebook visualization unresolved"

# Where the reference was found to be dead: while writing the notebook, while persisting it to
# the notebooks table, or while rendering it back to the user.
UnresolvedStage = Literal["create", "save", "render"]


def report_unresolved_notebook_visualizations(
    *,
    team: Team,
    notebook_artifact_id: str | None,
    unresolved_artifact_ids: list[str],
    stage: UnresolvedStage,
    user: User | None = None,
) -> None:
    """Emit an event for chart references a notebook can no longer resolve.

    Without this the failure is invisible: the notebook still renders, only the charts are
    replaced by a placeholder, so nobody finds out the report shipped broken.
    """
    if not unresolved_artifact_ids:
        return

    posthoganalytics.capture(
        distinct_id=user.distinct_id if user else str(team.uuid),
        event=UNRESOLVED_VISUALIZATION_EVENT,
        properties={
            "notebook_artifact_id": notebook_artifact_id,
            "unresolved_artifact_ids": unresolved_artifact_ids,
            "unresolved_count": len(unresolved_artifact_ids),
            "stage": stage,
            "source": EventSource.POSTHOG_AI,
        },
        # Deliberately not passing the organization object - this runs in async context and
        # `groups()` resolves it from `team.organization_id` without touching the database.
        groups=groups(team=team),
    )
