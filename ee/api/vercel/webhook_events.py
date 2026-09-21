"""What PostHog does with one verified Vercel webhook event.

Separate from the view, because the transport around this endpoint is being replaced and the
handling is not. The caller decides what an outcome answers on the wire; nothing here does.
"""

from enum import StrEnum
from typing import Any

from django.conf import settings

import requests as outbound_requests
import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.organization_integration import OrganizationIntegration

from ee.billing.billing_manager import BillingManager, BillingServiceOpenInvoicesError
from ee.models import License
from ee.vercel.integration import VercelIntegration

logger = structlog.get_logger(__name__)

BILLING_EVENT_PREFIX = "marketplace.invoice."
DEAUTHORIZATION_EVENT = "integration-configuration.removed"

CROSS_REGION_PROXY_TIMEOUT = 10
# EU waits up to 30 seconds for the billing service, so the billing hop needs a longer read
# deadline. A shorter one makes US report a slow billing service as an unknown installation.
CROSS_REGION_BILLING_PROXY_TIMEOUT = (10, 35)
DEFAULT_US_DOMAIN = "us.posthog.com"
DEFAULT_EU_DOMAIN = "eu.posthog.com"


class VercelEventOutcome(StrEnum):
    """What handling one event concluded, for a caller that answers Vercel."""

    ACCEPTED = "accepted"
    # An event type this integration does not act on.
    IGNORED = "ignored"
    # The event named no installation, so there is nothing to look up.
    MISSING_CONFIG_ID = "missing_config_id"
    # A billing event for an installation no region holds.
    UNKNOWN_CONFIG = "unknown_config"


class VercelEventProcessingError(Exception):
    """Handling failed on our side, so the event was not processed."""


def _is_us_region() -> bool:
    us_domain = getattr(settings, "REGION_US_DOMAIN", DEFAULT_US_DOMAIN)
    return settings.SITE_URL == f"https://{us_domain}"


def _proxy_to_eu(
    raw_body: bytes,
    signature: str | None,
    timeout: float | tuple[float, float] = CROSS_REGION_PROXY_TIMEOUT,
) -> int | None:
    """Forward a webhook to EU. Returns the EU status code, or None on failure."""
    eu_domain = getattr(settings, "REGION_EU_DOMAIN", DEFAULT_EU_DOMAIN)
    target_url = f"https://{eu_domain}/webhooks/vercel"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if signature:
        headers["x-vercel-signature"] = signature

    try:
        response = outbound_requests.post(
            url=target_url,
            data=raw_body,
            headers=headers,
            timeout=timeout,
        )
        logger.info(
            "vercel_webhook_proxied_to_eu",
            status_code=response.status_code,
        )
        return response.status_code
    except outbound_requests.RequestException as e:
        logger.warning("vercel_webhook_proxy_to_eu_failed", error=str(e))
        return None


def extract_config_id(payload: dict[str, Any]) -> str | None:
    # Billing events use "installationId". Deauthorization events use "configuration.id".
    return payload.get("installationId") or payload.get("configuration", {}).get("id")


def is_billing_event(event_type: str | None) -> bool:
    return bool(event_type and event_type.startswith(BILLING_EVENT_PREFIX))


def is_deauthorization_event(event_type: str | None) -> bool:
    return event_type == DEAUTHORIZATION_EVENT


def _get_integration(config_id: str) -> OrganizationIntegration | None:
    try:
        return OrganizationIntegration.objects.select_related("organization").get(
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=config_id,
        )
    except OrganizationIntegration.DoesNotExist:
        return None


def _forward_to_billing_service(event_type: str, payload: dict[str, Any], integration: OrganizationIntegration) -> None:
    license = License.objects.first()
    if not license:
        raise ValueError("No license configured")

    billing_manager = BillingManager(license=license)
    billing_manager.handle_billing_provider_webhook(
        event_type=event_type,
        event_data=payload,
        organization=integration.organization,
        billing_provider="vercel",
    )


def _handle_deauthorization(
    config_id: str,
    raw_body: bytes,
    signature: str | None,
) -> VercelEventOutcome:
    integration = _get_integration(config_id)
    if integration:
        is_connectable = integration.config.get("type") == "connectable"
        logger.info(
            "vercel_webhook_deauthorize",
            config_id=config_id,
            org_id=str(integration.organization_id),
            is_connectable=is_connectable,
        )
        if is_connectable:
            integration.delete()
            return VercelEventOutcome.ACCEPTED
        try:
            VercelIntegration.delete_installation(config_id)
        except BillingServiceOpenInvoicesError as e:
            # Vercel ignores non-200 from webhooks and shows "Integration Deleted" regardless.
            # The marketplace DELETE API endpoint handles the actual blocking with 409.
            # Log the warning but accept the event to avoid misleading error tracking noise.
            logger.warning(
                "vercel_webhook_deauthorize_blocked_by_open_invoices",
                config_id=config_id,
                reason=e.message,
            )
        except Exception as e:
            logger.exception("vercel_webhook_deauthorize_delete_failed", config_id=config_id)
            capture_exception(e, {"config_id": config_id})
            raise VercelEventProcessingError(str(e)) from e
        return VercelEventOutcome.ACCEPTED

    if _is_us_region():
        logger.info("vercel_webhook_deauthorize_proxying_to_eu", config_id=config_id)
        eu_status = _proxy_to_eu(raw_body, signature)
        if eu_status is None or eu_status >= 300:
            logger.warning(
                "vercel_webhook_deauthorize_eu_proxy_non_ok",
                config_id=config_id,
                eu_status=eu_status,
            )
    else:
        logger.warning("vercel_webhook_deauthorize_unknown_config", config_id=config_id)

    # A deauthorization for an installation this region never held is still done with.
    return VercelEventOutcome.ACCEPTED


def _handle_billing(
    event_type: str,
    payload: dict[str, Any],
    config_id: str,
    raw_body: bytes,
    signature: str | None,
) -> VercelEventOutcome:
    integration = _get_integration(config_id)
    if not integration:
        # All Vercel webhooks arrive on US, so the installation can belong to EU.
        eu_status = (
            _proxy_to_eu(raw_body, signature, timeout=CROSS_REGION_BILLING_PROXY_TIMEOUT) if _is_us_region() else None
        )
        if eu_status is not None and eu_status < 300:
            logger.info("vercel_webhook_billing_proxied_to_eu", config_id=config_id, event_type=event_type)
            return VercelEventOutcome.ACCEPTED

        logger.warning(
            "vercel_webhook_unknown_config",
            config_id=config_id,
            event_type=event_type,
            eu_status=eu_status,
        )
        return VercelEventOutcome.UNKNOWN_CONFIG

    try:
        _forward_to_billing_service(event_type, payload, integration)
    except Exception as e:
        logger.exception("vercel_webhook_billing_error", event_type=event_type)
        capture_exception(e, {"config_id": config_id, "event_type": event_type})
        raise VercelEventProcessingError(str(e)) from e

    logger.info("vercel_webhook_processed", event_type=event_type, org_id=str(integration.organization_id))
    return VercelEventOutcome.ACCEPTED


def handle_vercel_event(
    *,
    event_type: str | None,
    payload: dict[str, Any],
    raw_body: bytes,
    signature: str | None,
) -> VercelEventOutcome:
    """Route one verified event. Raises `VercelEventProcessingError` when handling failed."""
    config_id = extract_config_id(payload)
    logger.info("vercel_webhook_received", event_type=event_type, config_id=config_id)

    if is_deauthorization_event(event_type):
        if not config_id:
            logger.error("vercel_webhook_deauthorize_missing_config_id")
            return VercelEventOutcome.MISSING_CONFIG_ID
        return _handle_deauthorization(config_id, raw_body, signature)

    if not is_billing_event(event_type):
        logger.info("vercel_webhook_non_billing_event", event_type=event_type)
        return VercelEventOutcome.IGNORED

    if not config_id:
        logger.error("vercel_webhook_missing_config_id", event_type=event_type)
        return VercelEventOutcome.MISSING_CONFIG_ID

    # Guaranteed by the is_billing_event check above.
    assert event_type is not None
    return _handle_billing(event_type, payload, config_id, raw_body, signature)
