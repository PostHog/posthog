from typing import Optional, Union

from django.conf import settings

from posthog.models import organization
from posthog.models.organization import Organization


# We disable all plugins under multi-tenancy. For safety. Eventually we will remove this block.
# For now, removing this in TEST mode, so that we can be sure plugins actually work in EE if/when needed.
def not_in_multi_tenancy():
    return settings.TEST or not getattr(settings, "MULTI_TENANCY", False)


def can_install_plugins_via_api(organization_or_id: Optional[Union[Organization, str]]):
    organization_id = (
        None
        if not organization_or_id
        else (organization_or_id if isinstance(organization_or_id, str) else organization_or_id.id)
    )
    return settings.PLUGINS_INSTALL_VIA_API and (
        not_in_multi_tenancy() or (organization_id and organization_id in settings.PLUGINS_CLOUD_WHITELISTED_ORG_IDS)
    )


def can_configure_plugins_via_api():
    return settings.PLUGINS_CONFIGURE_VIA_API and not_in_multi_tenancy()
