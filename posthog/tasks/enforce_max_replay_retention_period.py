import logging

from celery import shared_task

from posthog.constants import AvailableFeature
from posthog.models.team import Team

logger = logging.getLogger(__name__)


BATCH_SIZE = 100


def _parse_feature_to_retention(retention_feature: dict) -> str | None:
    if not retention_feature or not retention_feature.get("limit") or not retention_feature.get("unit"):
        return None

    retention_limit = retention_feature.get("limit")
    retention_unit = retention_feature.get("unit")

    match retention_unit.lower():
        case "day" | "days":
            highest_retention_entitlement = f"{retention_limit}d"
        case "month" | "months":
            if retention_limit < 12:
                highest_retention_entitlement = f"{retention_limit * 30}d"
            else:
                highest_retention_entitlement = f"{retention_limit // 12}y"
        case "year" | "years":
            highest_retention_entitlement = f"{retention_limit}y"
        case _:
            return None

    if highest_retention_entitlement not in ["30d", "90d", "1y", "5y"]:
        return None

    return highest_retention_entitlement


@shared_task(ignore_result=True)
def enforce_max_replay_retention_period() -> None:
    teams_to_update = []

    for team in Team.objects.exclude(session_recording_retention_period="legacy").only(
        "id", "organization", "session_recording_retention_period"
    ):
        retention_feature = team.organization.get_available_feature(AvailableFeature.SESSION_REPLAY_DATA_RETENTION)
        highest_retention_entitlement = _parse_feature_to_retention(retention_feature)
        current_retention = team.session_recording_retention_period

        if highest_retention_entitlement is not None:
            ordered_retention_periods = ["30d", "90d", "1y", "5y"]

            if current_retention in ordered_retention_periods:
                if ordered_retention_periods.index(current_retention) <= ordered_retention_periods.index(
                    highest_retention_entitlement
                ):
                    continue

            team.session_recording_retention_period = highest_retention_entitlement
            teams_to_update.append(team)
        else:
            logger.warning(
                f"Session Recording retention feature is misconfigured for organization {team.organization.id}"
            )

    Team.objects.bulk_update(teams_to_update, ["session_recording_retention_period"], batch_size=BATCH_SIZE)
