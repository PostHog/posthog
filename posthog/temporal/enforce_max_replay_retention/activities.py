from temporalio import activity

from posthog.constants import AvailableFeature
from posthog.models.team import Team
from posthog.session_recordings.data_retention import (
    parse_feature_to_entitlement,
    retention_violates_entitlement,
    validate_retention_period,
)
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.enforce_max_replay_retention.types import EnforceMaxReplayRetentionInput

LOGGER = get_write_only_logger()


@activity.defn(name="enforce-max-replay-retention")
async def enforce_max_replay_retention(input: EnforceMaxReplayRetentionInput) -> None:
    async with Heartbeater():
        logger = LOGGER.bind()
        teams_to_update = []
        query_counter = 0

        logger.info("Querying teams...")
        async for team in (
            Team.objects.exclude(session_recording_retention_period="legacy")
            .exclude(session_recording_retention_period="30d")
            .only("id", "name", "organization", "session_recording_retention_period")
        ):
            organization = await database_sync_to_async(lambda team: team.organization)(team)
            retention_feature = await database_sync_to_async(organization.get_available_feature)(
                AvailableFeature.SESSION_REPLAY_DATA_RETENTION
            )
            highest_retention_entitlement = parse_feature_to_entitlement(retention_feature)

            if not validate_retention_period(highest_retention_entitlement):
                logger.warning(
                    f"Session Recording retention feature is misconfigured for organization",
                    team_id=team.id,
                    team_name=team.name,
                    organization_id=organization.id,
                    retention_entitlement=highest_retention_entitlement,
                    raw_retention_feature=retention_feature,
                )
                continue

            assert highest_retention_entitlement is not None  # hold mypys hand

            current_retention = team.session_recording_retention_period

            if not validate_retention_period(current_retention):
                logger.warning(
                    f"Session Recording retention period is misconfigured for team",
                    team_id=team.id,
                    team_name=team.name,
                    organization_id=organization.id,
                    retention_period=current_retention,
                )
                continue

            if retention_violates_entitlement(current_retention, highest_retention_entitlement):
                team.session_recording_retention_period = highest_retention_entitlement
                teams_to_update.append(team)

                logger.info(
                    "Retention period setting forcibly reduced",
                    team_id=team.id,
                    team_name=team.name,
                    organization_id=organization.id,
                    retention_period_before=current_retention,
                    retention_period_after=highest_retention_entitlement,
                )

            query_counter += 1
            if query_counter >= input.batch_size:
                query_counter = 0
                logger.info(f"Processed {input.batch_size} teams...")

        if not input.dry_run:
            logger.info(f"Updating {len(teams_to_update)} teams...")
            await database_sync_to_async(Team.objects.bulk_update)(
                teams_to_update, ["session_recording_retention_period"], batch_size=input.batch_size
            )
        else:
            logger.info(f"DRY RUN: Would have updated {len(teams_to_update)} teams...")
