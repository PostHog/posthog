"""What PostHog does with one verified Vercel webhook event.

The transport around it is `posthog/ingress/`, which verifies the signature, forwards a delivery
the other region owns and answers Vercel. Nothing here decides a status code.
"""

from enum import StrEnum
from typing import Any

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.ingress.dispatch.database import bounded_statement_timeout
from posthog.ingress.vercel.provider import VERCEL_BILLING_EVENT, VERCEL_DEAUTHORIZATION_EVENT
from posthog.models.organization_integration import OrganizationIntegration

from ee.billing.billing_manager import BillingManager, BillingServiceOpenInvoicesError
from ee.models import License
from ee.vercel.integration import VercelIntegration

logger = structlog.get_logger(__name__)

BILLING_EVENT_PREFIX = f"{VERCEL_BILLING_EVENT}."

# The lookup is one indexed row and runs inside the request, before dispatch.
OWNERSHIP_LOOKUP_TIMEOUT_MS = 1000


class VercelEventOutcome(StrEnum):
    """What handling one event concluded, for a caller that answers Vercel."""

    ACCEPTED = "accepted"
    # An event type this integration does not act on.
    IGNORED = "ignored"
    # The event named no installation, so there is nothing to look up.
    MISSING_CONFIG_ID = "missing_config_id"
    # A billing event for an installation this region does not hold.
    UNKNOWN_CONFIG = "unknown_config"


class VercelEventProcessingError(Exception):
    """Handling failed on our side, so the event was not processed."""


def extract_config_id(payload: dict[str, Any]) -> str | None:
    # Billing events use "installationId". Deauthorization events use "configuration.id".
    return payload.get("installationId") or payload.get("configuration", {}).get("id")


def is_billing_event(event_type: str | None) -> bool:
    return bool(event_type and event_type.startswith(BILLING_EVENT_PREFIX))


def is_deauthorization_event(event_type: str | None) -> bool:
    return event_type == VERCEL_DEAUTHORIZATION_EVENT


def installation_is_local(config_id: str) -> bool:
    """Whether this region holds the installation, for the ingress ownership lookup."""
    with bounded_statement_timeout(OWNERSHIP_LOOKUP_TIMEOUT_MS, models=[OrganizationIntegration]):
        return OrganizationIntegration.objects.filter(
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=config_id,
        ).exists()


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


def _handle_deauthorization(config_id: str) -> VercelEventOutcome:
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

    # The other region holds it, and ingress has already forwarded the signed request there.
    logger.warning("vercel_webhook_deauthorize_unknown_config", config_id=config_id)
    return VercelEventOutcome.ACCEPTED


def _handle_billing(event_type: str, payload: dict[str, Any], config_id: str) -> VercelEventOutcome:
    integration = _get_integration(config_id)
    if not integration:
        logger.error("vercel_webhook_unknown_config", config_id=config_id)
        capture_exception(
            OrganizationIntegration.DoesNotExist(),
            {"config_id": config_id, "event_type": event_type},
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


def handle_vercel_event(*, event_type: str | None, payload: dict[str, Any]) -> VercelEventOutcome:
    """Route one verified event. Raises `VercelEventProcessingError` when handling failed."""
    config_id = extract_config_id(payload)
    logger.info("vercel_webhook_received", event_type=event_type, config_id=config_id)

    if is_deauthorization_event(event_type):
        if not config_id:
            logger.error("vercel_webhook_deauthorize_missing_config_id")
            return VercelEventOutcome.MISSING_CONFIG_ID
        return _handle_deauthorization(config_id)

    if not is_billing_event(event_type):
        logger.info("vercel_webhook_non_billing_event", event_type=event_type)
        return VercelEventOutcome.IGNORED

    if not config_id:
        logger.error("vercel_webhook_missing_config_id", event_type=event_type)
        return VercelEventOutcome.MISSING_CONFIG_ID

    # Guaranteed by the is_billing_event check above.
    assert event_type is not None
    return _handle_billing(event_type, payload, config_id)
