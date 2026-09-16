import structlog

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.logs.backend.models import LogsRetentionRule

logger = structlog.get_logger(__name__)

DEFAULT_LOGS_RETENTION_DAYS = 14
# Custom retention periods are whole 30-day months, so ingestion and billing can treat each one as a tier.
LOGS_RETENTION_MONTH_DAYS = 30
# 86 thirty-day months cover 7 calendar years, the same ceiling as events retention.
LOGS_RETENTION_MAX_MONTHS = 86
LOGS_RETENTION_MAX_DAYS = LOGS_RETENTION_MONTH_DAYS * LOGS_RETENTION_MAX_MONTHS
LOGS_RETENTION_BASE_TIERS_DAYS = frozenset({DEFAULT_LOGS_RETENTION_DAYS, 30})
LOGS_CUSTOM_RETENTION_FLAG = "logs-settings-custom-retention"
LOGS_RETENTION_PAID_FEATURE = AvailableFeature.LOGS_RETENTION_30D


def logs_retention_days_error(days: int, *, custom_retention_enabled: bool) -> str | None:
    """Return the validation message for a retention period, or None when it is accepted."""
    if days in LOGS_RETENTION_BASE_TIERS_DAYS:
        return None
    if not custom_retention_enabled:
        return f"retention_days must be one of {sorted(LOGS_RETENTION_BASE_TIERS_DAYS)}"
    if days <= 0 or days % LOGS_RETENTION_MONTH_DAYS != 0 or days > LOGS_RETENTION_MAX_DAYS:
        return (
            f"retention_days must be {DEFAULT_LOGS_RETENTION_DAYS} or a multiple of {LOGS_RETENTION_MONTH_DAYS} days, "
            f"up to {LOGS_RETENTION_MAX_DAYS}"
        )
    return None


def required_logs_retention_feature(days: int) -> AvailableFeature | None:
    return LOGS_RETENTION_PAID_FEATURE if days > DEFAULT_LOGS_RETENTION_DAYS else None


def reset_logs_retention_rules(rules: list[LogsRetentionRule]) -> None:
    """Reset each rule's retention period to the default, keeping its filters and enabled state."""
    for rule in rules:
        rule.config = {**rule.config, "retention_days": DEFAULT_LOGS_RETENTION_DAYS}
        # Ingestion tracks rule changes by version, the same as an API update.
        rule.version += 1
    LogsRetentionRule.objects.bulk_update(rules, ["config", "version"])


def reset_revoked_logs_retention(organization: Organization, revoked_feature_keys: set[str]) -> int:
    """Reset team Logs retention to the default when its required feature was revoked.

    Called from the billing feature-refresh paths (customer update messages, trial
    cancellation) so that cancellations immediately stop applying paid retention to
    newly ingested logs. The Temporal `retention_entitlements` workflow remains
    available for org-wide manual reconciliation.
    """
    if LOGS_RETENTION_PAID_FEATURE.value not in revoked_feature_keys:
        return 0

    teams = list(
        Team.objects.filter(
            organization=organization, logs_settings__retention_days__gt=DEFAULT_LOGS_RETENTION_DAYS
        ).only("id", "logs_settings")
    )
    for team in teams:
        # Preserve unrelated Logs settings such as JSON parsing and PII scrubbing.
        team.logs_settings = {**(team.logs_settings or {}), "retention_days": DEFAULT_LOGS_RETENTION_DAYS}

    rules = list(
        LogsRetentionRule.objects.filter(
            team__organization=organization, config__retention_days__gt=DEFAULT_LOGS_RETENTION_DAYS
        ).only("id", "config", "version")
    )

    if teams:
        Team.objects.bulk_update(teams, ["logs_settings"])
    if rules:
        reset_logs_retention_rules(rules)
    if teams or rules:
        logger.info(
            "Logs retention reset after entitlement revocation",
            organization_id=str(organization.id),
            teams_reset=len(teams),
            rules_reset=len(rules),
        )
    return len(teams)
