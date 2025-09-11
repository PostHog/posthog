from typing import Optional, Union
from uuid import UUID

from posthog.models.organization import Organization


def has_plugin_access_level(
    organization_or_id: Optional[Union[Organization, str, UUID]], min_access_level: int
) -> bool:
    if organization_or_id is None:
        return False
    organization: Organization = (
        organization_or_id
        if isinstance(organization_or_id, Organization)
        else Organization.objects.get(id=organization_or_id)
    )
    return organization.plugins_access_level >= min_access_level


def can_globally_manage_plugins(organization_or_id: Optional[Union[Organization, str, UUID]]) -> bool:
    return has_plugin_access_level(organization_or_id, Organization.PluginsAccessLevel.ROOT)


def can_install_plugins(organization_or_id: Optional[Union[Organization, str, UUID]]) -> bool:
    return has_plugin_access_level(organization_or_id, Organization.PluginsAccessLevel.INSTALL)


def can_configure_plugins(organization_or_id: Optional[Union[Organization, str, UUID]]) -> bool:
    return has_plugin_access_level(organization_or_id, Organization.PluginsAccessLevel.CONFIG)
