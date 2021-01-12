from typing import Optional, Union
from uuid import UUID

from django.conf import settings

from posthog.models import organization
from posthog.models.organization import Organization


# We disable Plugins on Cloud, except for whitelisted organizations
# Disregarding this in TEST mode, so that we can be sure plugins actually work in EE if/when needed
def guard_cloud(organization_or_id: Optional[Union[Organization, UUID]]):
    organization_id: Optional[str] = (
        None
        if not organization_or_id
        else str(organization_or_id if isinstance(organization_or_id, UUID) else organization_or_id.id)
    )
    return (
        settings.TEST
        or not getattr(settings, "MULTI_TENANCY", False)
        or (organization_id and organization_id in getattr(settings, "PLUGINS_CLOUD_WHITELISTED_ORG_IDS", []))
    )


def can_install_plugins_via_api(organization_or_id: Optional[Union[Organization, UUID]]):
    return settings.PLUGINS_INSTALL_VIA_API and guard_cloud(organization_or_id)


def can_configure_plugins_via_api(organization_or_id: Optional[Union[Organization, UUID]]):
    return settings.PLUGINS_CONFIGURE_VIA_API and guard_cloud(organization_or_id)
