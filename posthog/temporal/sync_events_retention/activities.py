from temporalio import activity

from posthog.constants import AvailableFeature
from posthog.models.team import Team
from posthog.models.team.event_retention import parse_events_feature_to_months
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.sync_events_retention.types import SyncEventsRetentionInput

LOGGER = get_write_only_logger()


@activity.defn(name="sync-events-retention")
async def sync_events_retention(input: SyncEventsRetentionInput) -> None:
    """Reconcile every team's events retention window with its billing entitlement.

    Events retention is plan-derived and not user-editable, so we set it outright — unlike replay enforcement, which
    only caps a user-chosen value. Teams with no entitlement default to 7 years, grandfathering existing paid teams.
    """
    async with Heartbeater():
        logger = LOGGER.bind()
        logger.info("Syncing events retention for all teams...")

        last_pk = 0
        total_processed = 0
        total_updated = 0

        while True:
            # Bounded keyset batches: pgbouncer disables server-side cursors, so iterating the full queryset
            # would materialize every team (with its joined organization row) in memory at once.
            teams = [
                team
                async for team in Team.objects.filter(pk__gt=last_pk)
                .order_by("pk")
                .select_related("organization")
                .only("id", "event_retention_months", "organization__available_product_features")[: input.batch_size]
            ]
            if not teams:
                break
            last_pk = teams[-1].pk

            teams_to_update: list[Team] = []
            for team in teams:
                retention_feature = team.organization.get_available_feature(
                    AvailableFeature.PRODUCT_ANALYTICS_DATA_RETENTION
                )
                target_months = parse_events_feature_to_months(retention_feature)
                if team.event_retention_months != target_months:
                    team.event_retention_months = target_months
                    teams_to_update.append(team)

            if teams_to_update and not input.dry_run:
                await Team.objects.abulk_update(teams_to_update, ["event_retention_months"])

            total_processed += len(teams)
            total_updated += len(teams_to_update)
            logger.info(f"Processed {total_processed} teams, {total_updated} updated so far...")

        if input.dry_run:
            logger.info(f"DRY RUN: Would have updated {total_updated} of {total_processed} teams")
        else:
            logger.info(f"Updated {total_updated} of {total_processed} teams")
