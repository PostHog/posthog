from typing import Optional, Union
from uuid import UUID

from django.conf import settings

from posthog.models.organization import Organization


def can_install_plugins_via_api(organization_or_id: Optional[Union[Organization, str, UUID]]) -> bool:
    if not settings.MULTI_TENANCY:
        return settings.PLUGINS_INSTALL_VIA_API
    if organization_or_id is None:
        return False
    organization: Organization = (
        organization_or_id
        if isinstance(organization_or_id, Organization)
        else Organization.objects.get(id=organization_or_id)
    )
    return organization.plugins_access_level >= Organization.PluginsAccessLevel.INSTALLATION


def can_configure_plugins_via_api(organization_or_id: Optional[Union[Organization, str, UUID]]) -> bool:
    if not settings.MULTI_TENANCY:
        return settings.PLUGINS_CONFIGURE_VIA_API
    if organization_or_id is None:
        return False
    organization: Organization = (
        organization_or_id
        if isinstance(organization_or_id, Organization)
        else Organization.objects.get(id=organization_or_id)
    )
    return organization.plugins_access_level >= Organization.PluginsAccessLevel.CONFIGURATION
