from typing import Optional, Union
from uuid import UUID

from posthog.models.organization import Organization


def can_globally_manage_plugins(organization_or_id: Optional[Union[Organization, str, UUID]],) -> bool:
    if organization_or_id is None:
        return False
    organization: Organization = (
        organization_or_id
        if isinstance(organization_or_id, Organization)
        else Organization.objects.get(id=organization_or_id)
    )
    return organization.plugins_access_level >= Organization.PluginsAccessLevel.ROOT


def can_install_plugins(
    organization_or_id: Optional[Union[Organization, str, UUID]],
    specific_organization_id: Optional[Union[str, UUID]] = None,
) -> bool:
    if organization_or_id is None:
        return False
    organization: Organization = (
        organization_or_id
        if isinstance(organization_or_id, Organization)
        else Organization.objects.get(id=organization_or_id)
    )
    if specific_organization_id and str(organization.id) != str(specific_organization_id):
        return False
    return organization.plugins_access_level >= Organization.PluginsAccessLevel.INSTALL


def can_configure_plugins(organization_or_id: Optional[Union[Organization, str, UUID]],) -> bool:
    if organization_or_id is None:
        return False
    organization: Organization = (
        organization_or_id
        if isinstance(organization_or_id, Organization)
        else Organization.objects.get(id=organization_or_id)
    )
    return organization.plugins_access_level >= Organization.PluginsAccessLevel.CONFIG


def can_view_plugins(organization_or_id: Optional[Union[Organization, str, UUID]]) -> bool:
    if organization_or_id is None:
        return False
    organization: Organization = (
        organization_or_id
        if isinstance(organization_or_id, Organization)
        else Organization.objects.get(id=organization_or_id)
    )
    return organization.plugins_access_level > Organization.PluginsAccessLevel.NONE
