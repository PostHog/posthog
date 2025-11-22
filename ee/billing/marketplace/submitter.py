from collections.abc import Callable
from dataclasses import dataclass

import structlog

from posthog.cloud_utils import get_cached_instance_license
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.models.organization_integration import OrganizationIntegration

from ee.billing.billing_manager import BillingManager
from ee.billing.marketplace.client import MarketplaceClient

logger = structlog.get_logger(__name__)

MARKETPLACE_INTEGRATION_KINDS = [OrganizationIntegration.OrganizationIntegrationKind.VERCEL]


@dataclass
class MarketplaceContext:
    """Immutable context for marketplace operations."""

    organization: Organization
    integration: OrganizationIntegration
    billing_manager: BillingManager


class MarketplaceSubmitter:
    """
    Orchestrates the marketplace submission flow: hydration -> submission.

    Stateless - all dependencies are resolved fresh for each operation.
    """

    def __init__(self, organization_id: str):
        self._organization_id = organization_id

    def submit_invoice(self, invoice_id: str) -> None:
        self._execute(
            hydrate=lambda ctx: ctx.billing_manager.get_marketplace_invoice(ctx.organization, invoice_id),
            context={"invoice_id": invoice_id},
        )

    def submit_usage(self) -> None:
        self._execute(
            hydrate=lambda ctx: ctx.billing_manager.get_marketplace_usage(ctx.organization),
            context={},
        )

    def _execute(self, hydrate: Callable[[MarketplaceContext], dict], context: dict) -> None:
        log_context = {"organization_id": self._organization_id, **context}

        try:
            ctx = self._build_context()
            hydration = hydrate(ctx)
            self._submit(ctx.integration, hydration)
            logger.info("Marketplace submission succeeded", **log_context)

        except OrganizationNotFound:
            logger.warning("Organization not found for marketplace submission", **log_context)
            capture_exception(
                Exception("Organization not found for marketplace submission"),
                log_context,
            )

        except IntegrationNotFound:
            logger.info("No marketplace integration found, skipping submission", **log_context)

        except LicenseNotConfigured:
            logger.warning("Billing not configured for marketplace submission", **log_context)

        except Exception as e:
            logger.exception("Marketplace submission failed", error=str(e), **log_context)
            capture_exception(e, log_context)
            raise

    def _build_context(self) -> MarketplaceContext:
        organization = self._get_organization()
        integration = self._get_integration()
        billing_manager = self._get_billing_manager()
        return MarketplaceContext(organization, integration, billing_manager)

    def _get_organization(self) -> Organization:
        try:
            return Organization.objects.get(id=self._organization_id)
        except Organization.DoesNotExist:
            raise OrganizationNotFound()

    def _get_integration(self) -> OrganizationIntegration:
        try:
            return OrganizationIntegration.objects.get(
                organization_id=self._organization_id,
                kind__in=MARKETPLACE_INTEGRATION_KINDS,
            )
        except OrganizationIntegration.DoesNotExist:
            raise IntegrationNotFound()

    def _get_billing_manager(self) -> BillingManager:
        license = get_cached_instance_license()
        if not license:
            raise LicenseNotConfigured()
        return BillingManager(license)

    def _submit(self, integration: OrganizationIntegration, hydration: dict) -> None:
        endpoint = hydration.get("endpoint")
        payload = hydration.get("payload")

        if not endpoint or payload is None:
            raise ValueError("Hydration response missing endpoint or payload")

        client = MarketplaceClient(integration)
        client.submit(endpoint, payload)


class OrganizationNotFound(Exception):
    pass


class IntegrationNotFound(Exception):
    pass


class LicenseNotConfigured(Exception):
    pass
