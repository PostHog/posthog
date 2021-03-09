from typing import Optional, Union
from uuid import UUID

from django.conf import settings

from posthog.models.organization import Organization


def can_root_plugins_via_api(
    organization_or_id: Optional[Union[Organization, str, UUID]],
    match_organization_id: Optional[Union[str, UUID]] = None,
) -> bool:
    if organization_or_id is None:
        return False
    organization: Organization = (
        organization_or_id
        if isinstance(organization_or_id, Organization)
        else Organization.objects.get(id=organization_or_id)
    )
    if match_organization_id and str(organization.id) != str(match_organization_id):
        return False
    return organization.plugins_access_level >= Organization.PluginsAccessLevel.ROOT


def can_install_plugins_via_api(
    organization_or_id: Optional[Union[Organization, str, UUID]],
    match_organization_id: Optional[Union[str, UUID]] = None,
) -> bool:
    if organization_or_id is None:
        return False
    organization: Organization = (
        organization_or_id
        if isinstance(organization_or_id, Organization)
        else Organization.objects.get(id=organization_or_id)
    )
    if match_organization_id and str(organization.id) != str(match_organization_id):
        return False
    return organization.plugins_access_level >= Organization.PluginsAccessLevel.INSTALL


def can_configure_plugins_via_api(
    organization_or_id: Optional[Union[Organization, str, UUID]],
    match_organization_id: Optional[Union[str, UUID]] = None,
) -> bool:
    if organization_or_id is None:
        return False
    organization: Organization = (
        organization_or_id
        if isinstance(organization_or_id, Organization)
        else Organization.objects.get(id=organization_or_id)
    )
    if match_organization_id and str(organization.id) != str(match_organization_id):
        return False
    return organization.plugins_access_level >= Organization.PluginsAccessLevel.CONFIG
