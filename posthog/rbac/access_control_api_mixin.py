from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from products.enterprise.backend.api.rbac.access_control import AccessControlViewSetMixin
else:
    try:
        from products.enterprise.backend.api.rbac.access_control import AccessControlViewSetMixin

    except ImportError:

        class AccessControlViewSetMixin:
            pass
