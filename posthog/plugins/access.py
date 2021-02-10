from typing import Optional, Union
from uuid import UUID

from django.conf import settings

from posthog.models import organization
from posthog.models.organization import Organization


def can_install_plugins_via_api(organization_or_id: Optional[Union[Organization, UUID]]):
    return settings.PLUGINS_INSTALL_VIA_API


def can_configure_plugins_via_api(organization_or_id: Optional[Union[Organization, UUID]]):
    return settings.PLUGINS_CONFIGURE_VIA_API
