from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ee.api.rbac.access_control import AccessControlViewSetMixin
else:
    try:
        from ee.api.rbac.access_control import AccessControlViewSetMixin

    except ImportError:

        class AccessControlViewSetMixin:
            pass
