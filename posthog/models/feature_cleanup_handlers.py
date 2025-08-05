"""
Handlers for cleaning up organization settings when features are removed.
"""

from django.dispatch import receiver

from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception
from posthog.models import Organization, OrganizationDomain
from posthog.models.signals import organization_features_changed
import structlog

logger = structlog.get_logger(__name__)


@receiver(organization_features_changed)
def handle_sso_enforcement_removal(sender, organization: Organization, removed_features: list[str], **kwargs):
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


@receiver(organization_features_changed)
def handle_saml_removal(sender, organization: Organization, removed_features: list[str], **kwargs):
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


@receiver(organization_features_changed)
def handle_automatic_provisioning_removal(sender, organization: Organization, removed_features: list[str], **kwargs):
    """Clean up automatic provisioning when feature is removed."""
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


@receiver(organization_features_changed)
def handle_rbac_removal(sender, organization: Organization, removed_features: list[str], **kwargs):
    if AvailableFeature.ROLE_BASED_ACCESS in removed_features:
        try:
            from ee.models import AccessControl, Role

            deleted_count = AccessControl.objects.filter(team__organization=organization).delete()[0]
            roles_deleted = Role.objects.filter(organization=organization).delete()[0]

            logger.info(
                "Cleared RBAC configuration",
                organization_id=organization.id,
                access_controls_deleted=deleted_count,
                roles_deleted=roles_deleted,
            )
        except Exception as e:
            capture_exception(e)


@receiver(organization_features_changed)
def handle_invite_settings_removal(sender, organization: Organization, removed_features: list[str], **kwargs):
    if AvailableFeature.ORGANIZATION_INVITE_SETTINGS in removed_features:
        try:
            organization.members_can_invite = True
            organization.save(update_fields=["members_can_invite"])

            logger.info("Reset invite settings to defaults", organization_id=organization.id)
        except Exception as e:
            capture_exception(e)
