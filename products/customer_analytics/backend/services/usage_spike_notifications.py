from typing import Any

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception

from products.customer_analytics.backend.constants import CUSTOMER_ANALYTICS_CSP_FLAG
from products.customer_analytics.backend.models import Account
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    SourceType,
    TargetType,
    create_notification,
    has_been_dispatched,
)

logger = structlog.get_logger(__name__)

TITLE_MAX_LENGTH = 100
BODY_MAX_LENGTH = 200


def notify_owners_of_usage_spike(
    *,
    spike_id: str,
    spikes: list[dict[str, Any]],
    organization_id: str | None = None,
    billing_id: str | None = None,
    stripe_customer_id: str | None = None,
    detected_at: str | None = None,
) -> None:
    """Notify a Customer-analytics account's CSM and Account Executive that billing detected a
    usage spike for that customer. Idempotent per (owner, spike). Never raises — the SQS consumer
    must ack the message regardless; failures are captured to error tracking."""
    try:
        account = _find_account(
            organization_id=organization_id,
            billing_id=billing_id,
            stripe_customer_id=stripe_customer_id,
        )
        if account is None:
            logger.info(
                "usage_spike.account_not_found",
                organization_id=organization_id,
                billing_id=billing_id,
                stripe_customer_id=stripe_customer_id,
            )
            return

        if not _is_csp_enabled(account):
            logger.info("usage_spike.csp_disabled", account_id=str(account.id))
            return

        owner_user_ids = _get_owner_user_ids(account)
        if not owner_user_ids:
            logger.info("usage_spike.no_owners", account_id=str(account.id))
            return

        title = f"Usage spike: {account.name}"[:TITLE_MAX_LENGTH]
        body = _build_body(spikes, detected_at)[:BODY_MAX_LENGTH]
        # No per-account detail route exists, so deep-link to the accounts list.
        source_url = f"/project/{account.team.project_id}/customer_analytics/accounts"

        for user_id in owner_user_ids:
            _notify_owner(
                account=account,
                user_id=user_id,
                spike_id=spike_id,
                title=title,
                body=body,
                source_url=source_url,
            )
    except Exception as e:
        capture_exception(e)
        logger.exception("usage_spike.dispatch_failed", spike_id=spike_id)


def _find_account(
    *,
    organization_id: str | None,
    billing_id: str | None,
    stripe_customer_id: str | None,
) -> Account | None:
    candidates = Account.objects.unscoped().select_related("team").order_by("created_at")
    for lookup, value in (
        ("external_id", organization_id),
        ("_properties__billing_id", billing_id),
        ("_properties__stripe_customer_id", stripe_customer_id),
    ):
        if not value:
            continue
        # Fetch up to 2 to detect (and warn about) an ambiguous cross-team match without loading all rows.
        matches = list(candidates.filter(**{lookup: str(value)})[:2])
        if not matches:
            continue
        if len(matches) > 1:
            logger.warning("usage_spike.multiple_accounts_matched", lookup=lookup, value=str(value))
        return matches[0]
    return None


def _is_csp_enabled(account: Account) -> bool:
    organization_id = str(account.team.organization_id)
    return bool(
        posthoganalytics.feature_enabled(
            CUSTOMER_ANALYTICS_CSP_FLAG,
            organization_id,
            groups={"organization": organization_id},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


def _get_owner_user_ids(account: Account) -> list[int]:
    properties = account.properties
    user_ids: list[int] = []
    for assignment in (properties.csm, properties.account_executive):
        if assignment is not None and assignment.id not in user_ids:
            user_ids.append(assignment.id)
    return user_ids


def _build_body(spikes: list[dict[str, Any]], detected_at: str | None) -> str:
    summary = _summarize_spikes(spikes)
    return f"{summary} — detected {detected_at}" if detected_at else summary


def _summarize_spikes(spikes: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for spike in spikes:
        metric = spike.get("metric") or "usage"
        factor = spike.get("factor")
        direction = spike.get("direction") or "up"
        parts.append(f"{metric} {factor}× ({direction})" if factor is not None else str(metric))
    return ", ".join(parts) if parts else "Unusual usage detected"


def _notify_owner(
    *,
    account: Account,
    user_id: int,
    spike_id: str,
    title: str,
    body: str,
    source_url: str,
) -> None:
    try:
        if has_been_dispatched(
            notification_type=NotificationType.USAGE_SPIKE,
            target_type=TargetType.USER,
            target_id=str(user_id),
            resource_id=str(account.id),
            source_id=spike_id,
        ):
            return
        create_notification(
            NotificationData(
                team_id=account.team_id,
                notification_type=NotificationType.USAGE_SPIKE,
                priority=Priority.NORMAL,
                title=title,
                body=body,
                target_type=TargetType.USER,
                target_id=str(user_id),
                resource_type=None,
                resource_id=str(account.id),
                source_url=source_url,
                source_type=SourceType.CUSTOMER_ANALYTICS,
                source_id=spike_id,
            )
        )
    except Exception as e:
        capture_exception(e)
        logger.exception("usage_spike.notify_failed", account_id=str(account.id), user_id=user_id)
