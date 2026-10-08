import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.utils import timezone
from django.utils.dateparse import parse_datetime

import structlog

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.logs.backend.models import LogsRetentionRule

if TYPE_CHECKING:
    from products.tracing.backend.facade.retention import TracesRetentionRule

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


# A retention change only applies to records ingested after it, so a period that flaps back and
# forth leaves the data behind it impossible to reason about. One change a day is enough.
RETENTION_UPDATE_THROTTLE_HOURS = 24


def retention_update_throttle_error(last_updated: datetime | str | None) -> str | None:
    """Return the throttle message when the period was changed too recently, or None."""
    if not last_updated:
        return None
    parsed = parse_datetime(last_updated) if isinstance(last_updated, str) else last_updated
    if parsed is None:
        return None
    time_since_update = timezone.now() - parsed
    if time_since_update >= timedelta(hours=RETENTION_UPDATE_THROTTLE_HOURS):
        return None
    hours_remaining = RETENTION_UPDATE_THROTTLE_HOURS - (time_since_update.total_seconds() / 3600)
    return (
        f"You can only update retention settings once per {RETENTION_UPDATE_THROTTLE_HOURS} hours. "
        f"Please wait {math.ceil(hours_remaining)} more hour(s)."
    )


def _set_default_period(rules: Sequence["LogsRetentionRule | TracesRetentionRule"]) -> None:
    for rule in rules:
        rule.config = {**rule.config, "retention_days": DEFAULT_LOGS_RETENTION_DAYS}
        # Ingestion tracks rule changes by version, the same as an API update.
        rule.version += 1


def reset_logs_retention_rules(rules: list[LogsRetentionRule]) -> None:
    """Reset each rule's retention period to the default, keeping its filters and enabled state."""
    _set_default_period(rules)
    LogsRetentionRule.objects.bulk_update(rules, ["config", "version"])


def reset_span_retention_rules(rules: list["TracesRetentionRule"], *, batch_size: int | None = None) -> None:
    """The span-rule counterpart of `reset_logs_retention_rules`."""
    # Imported here so the tracing product stays off this module's import path.
    from products.tracing.backend.facade.retention import TracesRetentionRule  # noqa: PLC0415

    _set_default_period(rules)
    # The rules come from several environments, so this write is deliberately unscoped.
    TracesRetentionRule.objects.unscoped().bulk_update(rules, ["config", "version"], batch_size=batch_size)


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

    # Rules store their own period, so ingestion keeps applying a paid period until they are reset too.
    rules = list(
        LogsRetentionRule.objects.filter(
            team__organization=organization, config__retention_days__gt=DEFAULT_LOGS_RETENTION_DAYS
        ).only("id", "config", "version")
    )

    # Imported here so the tracing product stays off this module's import path.
    from products.tracing.backend.facade.retention import TracesRetentionRule  # noqa: PLC0415
    from products.tracing.backend.facade.team_extension import TeamTracingConfig  # noqa: PLC0415

    # Traces reuse the Logs entitlement, so their default period and span rules are reset with it.
    tracing_configs = list(
        TeamTracingConfig.objects.filter(
            team__organization=organization, retention_days__gt=DEFAULT_LOGS_RETENTION_DAYS
        ).only("team_id", "retention_days")
    )
    for config in tracing_configs:
        config.retention_days = DEFAULT_LOGS_RETENTION_DAYS
    # The organization spans several environments, so this read is deliberately unscoped.
    span_rules = list(
        TracesRetentionRule.objects.unscoped()
        .filter(team__organization=organization, config__retention_days__gt=DEFAULT_LOGS_RETENTION_DAYS)
        .only("id", "config", "version")
    )

    if teams:
        Team.objects.bulk_update(teams, ["logs_settings"])
    if tracing_configs:
        TeamTracingConfig.objects.bulk_update(tracing_configs, ["retention_days"])
    if rules:
        reset_logs_retention_rules(rules)
    if span_rules:
        reset_span_retention_rules(span_rules)
    if teams or rules or tracing_configs or span_rules:
        logger.info(
            "Logs retention reset after entitlement revocation",
            organization_id=str(organization.id),
            teams_reset=len(teams),
            rules_reset=len(rules),
            tracing_configs_reset=len(tracing_configs),
            span_rules_reset=len(span_rules),
        )
    return len(teams)


def reset_unentitled_traces_retention(*, dry_run: bool, batch_size: int) -> int:
    """Reset the traces default to the free tier wherever the organization lacks the Logs retention feature.

    The Logs retention reconciliation activity calls this, so the logs product never imports the
    tracing product. Returns how many configs were reset, or would be on a dry run.
    """
    # Imported here so the tracing product stays off this module's import path.
    from products.tracing.backend.facade.team_extension import TeamTracingConfig  # noqa: PLC0415

    to_update = []
    for config in (
        TeamTracingConfig.objects.filter(retention_days__gt=DEFAULT_LOGS_RETENTION_DAYS)
        .select_related("team__organization")
        .only("team__id", "retention_days", "team__organization__available_product_features")
    ):
        required_feature = required_logs_retention_feature(config.retention_days)
        organization = config.team.organization
        if not required_feature or organization.is_feature_available(required_feature):
            continue
        logger.info(
            "Traces retention period setting forcibly reduced",
            team_id=config.team_id,
            organization_id=organization.id,
            retention_period_before=config.retention_days,
            retention_period_after=DEFAULT_LOGS_RETENTION_DAYS,
        )
        config.retention_days = DEFAULT_LOGS_RETENTION_DAYS
        to_update.append(config)

    if not dry_run and to_update:
        TeamTracingConfig.objects.bulk_update(to_update, ["retention_days"], batch_size=batch_size)
    return len(to_update)


def reset_unentitled_span_retention_rules(*, dry_run: bool, batch_size: int) -> int:
    """The span-rule counterpart of `reset_unentitled_traces_retention`. Returns how many rules were reset."""
    # Imported here so the tracing product stays off this module's import path.
    from products.tracing.backend.facade.retention import TracesRetentionRule  # noqa: PLC0415

    to_update = []
    # A sweep over every environment, so this read is deliberately unscoped.
    for rule in (
        TracesRetentionRule.objects.unscoped()
        .filter(config__retention_days__gt=DEFAULT_LOGS_RETENTION_DAYS)
        .select_related("team__organization")
        .only("id", "config", "version", "team__id", "team__organization__available_product_features")
    ):
        retention_days = rule.config.get("retention_days")
        if not isinstance(retention_days, int):
            continue
        required_feature = required_logs_retention_feature(retention_days)
        organization = rule.team.organization
        if not required_feature or organization.is_feature_available(required_feature):
            continue
        logger.info(
            "Traces retention rule period forcibly reduced",
            rule_id=str(rule.id),
            team_id=rule.team_id,
            organization_id=organization.id,
            retention_period_before=retention_days,
            retention_period_after=DEFAULT_LOGS_RETENTION_DAYS,
        )
        to_update.append(rule)

    if not dry_run and to_update:
        reset_span_retention_rules(to_update, batch_size=batch_size)
    return len(to_update)
