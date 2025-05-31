from typing import cast
from uuid import UUID

from celery import shared_task
from structlog import get_logger

from posthog.event_usage import report_user_action
from posthog.models import Project, User
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.signals import mute_selected_signals
from posthog.models.team.util import delete_batch_exports, delete_bulky_postgres_data
from posthog.models.utils import UUIDT
from posthog.tasks.utils import CeleryQueue

logger = get_logger(__name__)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=3600,
)
def delete_project_async(
    project_id: int,
    organization_id: UUID,
    project_name: str,
    user_id: int,
    was_impersonated: bool = False,
) -> None:
    """
    Asynchronously delete a project and all associated data.

    This task handles the heavy lifting of project deletion, including:
    - Deleting bulky PostgreSQL data
    - Deleting batch exports
    - Creating AsyncDeletion entries for ClickHouse data cleanup
    - Logging activity for audit trail
    """
    try:
        logger.info(
            "Starting async project deletion",
            project_id=project_id,
            organization_id=organization_id,
            user_id=user_id,
        )

        # Get the user who initiated the deletion
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            logger.warning("User not found for project deletion", user_id=user_id, project_id=project_id)
            user = None

        # Get the project and its teams
        try:
            project = Project.objects.get(pk=project_id)
            teams = list(project.teams.only("id", "uuid", "name", "organization_id").all())
        except Project.DoesNotExist:
            logger.warning("Project already deleted", project_id=project_id)
            return

        # Delete bulky PostgreSQL data and batch exports
        team_ids = [team.id for team in teams]
        delete_bulky_postgres_data(team_ids=team_ids)
        delete_batch_exports(team_ids=team_ids)

        # Delete the project with muted signals to avoid cascading effects
        with mute_selected_signals():
            project.delete()

        # Create AsyncDeletion entries for ClickHouse data cleanup
        if user:
            AsyncDeletion.objects.bulk_create(
                [
                    AsyncDeletion(
                        deletion_type=DeletionType.Team,
                        team_id=team.id,
                        key=str(team.id),
                        created_by=user,
                    )
                    for team in teams
                ],
                ignore_conflicts=True,
            )

        # Log activity for each team deletion
        for team in teams:
            if user:
                log_activity(
                    organization_id=cast(UUIDT, organization_id),
                    team_id=team.pk,
                    user=user,
                    was_impersonated=was_impersonated,
                    scope="Team",
                    item_id=team.pk,
                    activity="deleted",
                    detail=Detail(name=str(team.name)),
                )
                report_user_action(user, "team deleted", team=team)

        # Log project deletion activity
        if user:
            log_activity(
                organization_id=cast(UUIDT, organization_id),
                team_id=project_id,
                user=user,
                was_impersonated=was_impersonated,
                scope="Project",
                item_id=project_id,
                activity="deleted",
                detail=Detail(name=str(project_name)),
            )
            report_user_action(
                user,
                "project deleted",
                {"project_name": project_name},
                team=teams[0] if teams else None,
            )

        logger.info(
            "Successfully completed async project deletion",
            project_id=project_id,
            organization_id=organization_id,
            teams_deleted=len(teams),
        )

    except Exception as e:
        logger.error(
            "Error during async project deletion",
            project_id=project_id,
            organization_id=organization_id,
            error=str(e),
            exc_info=True,
        )
        raise
