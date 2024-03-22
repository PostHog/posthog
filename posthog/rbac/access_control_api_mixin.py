from typing import TYPE_CHECKING


try:
    from ee.api.rbac.access_control import AccessControlViewSetMixin as _AccessControlViewSetMixin
except ImportError:

    class FakeAccessControlViewSetMixin:
        pass

    _AccessControlViewSetMixin = FakeAccessControlViewSetMixin


AccessControlViewSetMixin = _AccessControlViewSetMixin
