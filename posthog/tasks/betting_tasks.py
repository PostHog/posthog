import logging

from celery import shared_task

from posthog.models.betting import BetDefinition
from posthog.betting.betting_utils import refresh_probability_distribution

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def refresh_all_probability_distributions() -> None:
    """
    Task to refresh probability distributions for all active bet definitions.
    This task should be scheduled to run periodically.
    """
    logger.info("Starting refresh of all probability distributions")

    # Get all active bet definitions
    active_bet_definitions = BetDefinition.objects.filter(status=BetDefinition.Status.ACTIVE)

    refreshed_count = 0
    failed_count = 0

    for bet_definition in active_bet_definitions:
        try:
            # Check if it's time to refresh this distribution based on the interval
            should_refresh = True
            latest_distribution = bet_definition.latest_probability_distribution

            if latest_distribution:
                # Only refresh if the interval has passed
                from django.utils import timezone
                import datetime

                interval_seconds = bet_definition.probability_distribution_interval
                time_since_last_refresh = timezone.now() - latest_distribution.created_at

                if time_since_last_refresh < datetime.timedelta(seconds=interval_seconds):
                    should_refresh = False

            if should_refresh:
                result = refresh_probability_distribution(bet_definition.id)
                if result:
                    refreshed_count += 1
                else:
                    failed_count += 1
        except Exception as e:
            logger.exception(f"Error refreshing probability distribution for bet definition {bet_definition.id}: {e}")
            failed_count += 1

    logger.info(f"Completed refresh of probability distributions. Refreshed: {refreshed_count}, Failed: {failed_count}")


@shared_task(ignore_result=True)
def refresh_probability_distribution_task(bet_definition_id: str) -> None:
    """
    Task to refresh a single probability distribution.

    Args:
        bet_definition_id: The ID of the bet definition to refresh
    """
    logger.info(f"Refreshing probability distribution for bet definition {bet_definition_id}")

    try:
        result = refresh_probability_distribution(bet_definition_id)
        if result:
            logger.info(f"Successfully refreshed probability distribution for bet definition {bet_definition_id}")
        else:
            logger.error(f"Failed to refresh probability distribution for bet definition {bet_definition_id}")
    except Exception as e:
        logger.exception(f"Error refreshing probability distribution for bet definition {bet_definition_id}: {e}")
