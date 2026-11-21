from collections.abc import Callable

from django.dispatch import Signal

role_access_invalidated = Signal()
role_access_changed = Signal()


def connect_role_access_invalidated(receiver: Callable[..., None], *, dispatch_uid: str) -> None:
    """Clear request-local permission state synchronously, including inside a transaction."""
    role_access_invalidated.connect(receiver, dispatch_uid=dispatch_uid, weak=False)


def connect_role_access_changed(receiver: Callable[..., None], *, dispatch_uid: str) -> None:
    """Refresh external access after commit and membership-cache invalidation.

    The receiver gets ``user_id`` and ``organization_id`` for each affected membership.
    """
    role_access_changed.connect(receiver, dispatch_uid=dispatch_uid, weak=False)
