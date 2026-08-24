from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from products.access_control.backend.facade.access_control import AccessControlViewSetMixin
    from products.access_control.backend.facade.access_control_settings import AccessControlSettingsViewSetMixin
else:
    try:
        from products.access_control.backend.facade.access_control import AccessControlViewSetMixin

    except ImportError:

        class AccessControlViewSetMixin:
            pass

    try:
        from products.access_control.backend.facade.access_control_settings import AccessControlSettingsViewSetMixin

    except ImportError:

        class AccessControlSettingsViewSetMixin:
            pass
