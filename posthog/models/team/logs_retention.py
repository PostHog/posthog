import structlog

from posthog.constants import LOGS_RETENTION_FEATURES_BY_DAYS
from posthog.models.organization import Organization
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

DEFAULT_LOGS_RETENTION_DAYS = 14


def reset_revoked_logs_retention(organization: Organization, revoked_feature_keys: set[str]) -> int:
    """Reset team Logs retention to the default when its required feature was revoked.

    Called from the billing feature-refresh paths (customer update messages, trial
    cancellation) so that cancellations immediately stop applying paid retention to
    newly ingested logs. The Temporal `retention_entitlements` workflow remains
    available for org-wide manual reconciliation.
    """
    revoked_days = [
        days for days, feature in LOGS_RETENTION_FEATURES_BY_DAYS.items() if feature.value in revoked_feature_keys
    ]
    if not revoked_days:
        return 0

    teams = list(
        Team.objects.filter(organization=organization, logs_settings__retention_days__in=revoked_days).only(
            "id", "logs_settings"
        )
    )
    for team in teams:
        # Preserve unrelated Logs settings such as JSON parsing and PII scrubbing.
        team.logs_settings = {**(team.logs_settings or {}), "retention_days": DEFAULT_LOGS_RETENTION_DAYS}

    if teams:
        Team.objects.bulk_update(teams, ["logs_settings"])
        logger.info(
            "Logs retention reset after entitlement revocation",
            organization_id=str(organization.id),
            teams_reset=len(teams),
        )
    return len(teams)
