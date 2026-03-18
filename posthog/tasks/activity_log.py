import structlog
from celery import shared_task

from posthog.cdp.internal_events import InternalEventEvent, InternalEventPerson, produce_internal_event
from posthog.models import Team

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def broadcast_activity_log_to_organization(organization_id: str, serialized_data: dict, user_data: dict | None) -> None:
    """
    Broadcast an activity log event to all teams that have opted in to receive
    organization-level activity log notifications.
    """
    try:
        # Find all teams in the org that want notifications
        subscribed_teams = list(
            Team.objects.filter(
                organization_id=organization_id,
                receive_org_level_activity_logs=True,
            ).values_list("id", flat=True)
        )

        if not subscribed_teams:
            return

        for team_id in subscribed_teams:
            try:
                produce_internal_event(
                    team_id=team_id,
                    event=InternalEventEvent(
                        event="$activity_log_entry_created",
                        distinct_id=user_data["distinct_id"] if user_data else f"team_{team_id}",
                        properties=serialized_data,
                    ),
                    person=(
                        InternalEventPerson(
                            id=user_data["id"],
                            properties=user_data,
                        )
                        if user_data
                        else None
                    ),
                )
                logger.debug(
                    f"Produced activity log event for team",
                    organization_id=organization_id,
                    team_id=team_id,
                )
            except Exception as e:
                logger.exception(
                    f"Error producing activity log event for team",
                    organization_id=organization_id,
                    team_id=team_id,
                    error=str(e),
                )

    except Exception as e:
        logger.exception(
            f"Error broadcasting activity log for organization {organization_id}",
            organization_id=organization_id,
            error=str(e),
        )
        raise
