from django.db.models.signals import post_save
from django.dispatch import receiver
import structlog

from posthog.models.team.team import Team
from posthog.tasks.web_analytics_backfill import backfill_web_analytics_tables_for_team

logger = structlog.get_logger(__name__)


@receiver(post_save, sender=Team)
def handle_web_analytics_pre_aggregated_tables_enabled(sender, instance, **kwargs):
    """
    Trigger automatic backfill when web_analytics_pre_aggregated_tables_enabled changes to True.

    This provides immediate response to team setting changes, replacing the over-engineered
    Dagster scanning approach with a simple event-driven mechanism.
    """
    if not kwargs.get('created', False):  # Only for updates, not new team creation
        # Check if the specific field was updated
        if hasattr(instance, '_state') and instance._state.adding:
            return  # Skip for new objects

        try:
            # Get the previous state to check if the field changed
            old_instance = Team.objects.get(pk=instance.pk)
            old_value = old_instance.web_analytics_pre_aggregated_tables_enabled
            new_value = instance.web_analytics_pre_aggregated_tables_enabled

            # Trigger backfill if changed from False/None to True
            if not old_value and new_value:
                logger.info(
                    "Web analytics pre-aggregated tables enabled for team, triggering backfill",
                    team_id=instance.pk,
                    team_name=instance.name,
                )

                # Async trigger the backfill task
                backfill_web_analytics_tables_for_team.delay(instance.pk)

        except Team.DoesNotExist:
            # Handle edge case where team was just created
            pass
        except Exception as e:
            logger.error(
                "Failed to trigger web analytics backfill",
                team_id=instance.pk,
                error=str(e),
                exc_info=True,
            )
