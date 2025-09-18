import logging

from celery import shared_task

from posthog.constants import AvailableFeature
from posthog.models.team import Team
from posthog.ph_client import get_client
from posthog.session_recordings.data_retention import (
    parse_feature_to_entitlement,
    retention_violates_entitlement,
    validate_retention_period,
)

logger = logging.getLogger(__name__)


BATCH_SIZE = 100


@shared_task(ignore_result=True)
def enforce_max_replay_retention_period() -> None:
    ph_client = get_client()
    teams_to_update = []

    for team in (
        Team.objects.exclude(session_recording_retention_period="legacy")
        .exclude(session_recording_retention_period="30d")
        .only("id", "name", "organization", "session_recording_retention_period")
    ):
        retention_feature = team.organization.get_available_feature(AvailableFeature.SESSION_REPLAY_DATA_RETENTION)
        highest_retention_entitlement = parse_feature_to_entitlement(retention_feature)

        if not validate_retention_period(highest_retention_entitlement):
            logger.warning(
                f"Session Recording retention feature is misconfigured for organization {team.organization.id}"
            )
            continue

        assert highest_retention_entitlement is not None  # hold mypys hand

        current_retention = team.session_recording_retention_period

        if not validate_retention_period(current_retention):
            logger.warning(f"Session Recording retention period is misconfigured for team {team.id}")
            continue

        if retention_violates_entitlement(current_retention, highest_retention_entitlement):
            team.session_recording_retention_period = highest_retention_entitlement
            teams_to_update.append(team)

            ph_client.capture(
                event="retention period setting forcibly reduced",
                properties={
                    "team_id": team.id,
                    "team_name": team.name,
                    "organization_id": team.organization.id,
                    "retention_period_before": current_retention,
                    "retention_period_after": highest_retention_entitlement,
                },
            )

    Team.objects.bulk_update(teams_to_update, ["session_recording_retention_period"], batch_size=BATCH_SIZE)
    ph_client.shutdown()
