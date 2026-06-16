from temporalio import activity

from posthog.constants import AvailableFeature
from posthog.models.team import Team
from posthog.models.team.event_retention import parse_events_feature_to_period
from posthog.sync import database_sync_to_async
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
        teams_to_update = []
        query_counter = 0

        logger.info("Syncing events retention for all teams...")
        async for team in Team.objects.only("id", "name", "organization", "event_retention_period"):
            organization = await database_sync_to_async(lambda team: team.organization)(team)
            retention_feature = await database_sync_to_async(organization.get_available_feature)(
                AvailableFeature.EVENT_DATA_RETENTION
            )
            target_period = parse_events_feature_to_period(retention_feature)

            if team.event_retention_period != target_period:
                logger.info(
                    "Events retention period synced",
                    team_id=team.id,
                    team_name=team.name,
                    organization_id=organization.id,
                    retention_period_before=team.event_retention_period,
                    retention_period_after=target_period,
                )
                team.event_retention_period = target_period
                teams_to_update.append(team)

            query_counter += 1
            if query_counter >= input.batch_size:
                query_counter = 0
                logger.info(f"Processed {input.batch_size} teams...")

        if not input.dry_run:
            logger.info(f"Updating {len(teams_to_update)} teams...")
            await database_sync_to_async(Team.objects.bulk_update)(
                teams_to_update, ["event_retention_period"], batch_size=input.batch_size
            )
        else:
            logger.info(f"DRY RUN: Would have updated {len(teams_to_update)} teams...")
