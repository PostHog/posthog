import posthoganalytics

from posthog import event_usage
from posthog.event_usage import EventSource
from posthog.models import Team
from posthog.sync import database_sync_to_async

# Shown in place of a chart whose reference resolves to no query. The raw artifact id helped
# nobody; this tells the reader what happened and what to do next.
UNRESOLVED_VISUALIZATION_MESSAGE = "Couldn't load this chart. Ask Max to rebuild it."

UNRESOLVED_VISUALIZATION_EVENT = "ai notebook visualization unresolved"


async def areport_unresolved_notebook_visualizations(
    *,
    team: Team,
    notebook_artifact_id: str | None,
    unresolved_artifact_ids: list[str],
) -> None:
    """Emit an event for chart references a notebook can no longer resolve.

    Without this the failure is invisible: the notebook still renders, only the charts are
    replaced by a placeholder, so nobody finds out the report shipped broken.
    """
    if not unresolved_artifact_ids:
        return

    await database_sync_to_async(posthoganalytics.capture)(
        distinct_id=str(team.uuid),
        event=UNRESOLVED_VISUALIZATION_EVENT,
        properties={
            "notebook_artifact_id": notebook_artifact_id,
            "unresolved_artifact_ids": unresolved_artifact_ids,
            "unresolved_count": len(unresolved_artifact_ids),
            "source": EventSource.POSTHOG_AI,
        },
        groups=event_usage.groups(team=team),
    )
