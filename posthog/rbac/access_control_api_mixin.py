from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ee.api.rbac.access_control import AccessControlViewSetMixin
    from ee.api.rbac.access_control_settings import AccessControlSettingsViewSetMixin
else:
    try:
        from ee.api.rbac.access_control import AccessControlViewSetMixin

    except ImportError:

        class AccessControlViewSetMixin:
            pass

    try:
        from ee.api.rbac.access_control_settings import AccessControlSettingsViewSetMixin

    except ImportError:

        class AccessControlSettingsViewSetMixin:
            pass
