from celery import shared_task

from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception

from structlog import get_logger

logger = get_logger(__name__)


@shared_task(ignore_result=True)
def organization_feature_cleanup(organization_id: int, removed_features: list[str]) -> None:
    from posthog.models import Organization, OrganizationDomain

    organization = Organization.objects.get(id=organization_id)

    if AvailableFeature.SSO_ENFORCEMENT in removed_features:
        try:
            updated = OrganizationDomain.objects.filter(organization=organization).update(sso_enforcement="")

            if updated > 0:
                logger.info(
                    "Cleared SSO enforcement for organization domains",
                    organization_id=organization.id,
                    domains_updated=updated,
                )
        except Exception as e:
            capture_exception(e)

    if AvailableFeature.SAML in removed_features:
        try:
            updated = OrganizationDomain.objects.filter(organization=organization).update(
                saml_entity_id=None, saml_acs_url=None, saml_x509_cert=None
            )

            if updated > 0:
                logger.info(
                    "Cleared SAML configuration for organization domains",
                    organization_id=organization.id,
                    domains_updated=updated,
                )
        except Exception as e:
            capture_exception(e)

    if AvailableFeature.AUTOMATIC_PROVISIONING in removed_features:
        try:
            updated = OrganizationDomain.objects.filter(organization=organization).update(
                jit_provisioning_enabled=False
            )

            if updated > 0:
                logger.info(
                    "Disabled JIT provisioning for organization domains",
                    organization_id=organization.id,
                    domains_updated=updated,
                )
        except Exception as e:
            capture_exception(e)

    if AvailableFeature.ORGANIZATION_INVITE_SETTINGS in removed_features:
        try:
            organization.members_can_invite = True
            organization.save(update_fields=["members_can_invite"])

            logger.info("Reset invite settings to defaults", organization_id=organization.id)
        except Exception as e:
            capture_exception(e)
