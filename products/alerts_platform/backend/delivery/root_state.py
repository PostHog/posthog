"""The current-state line an edited root message shows.

Built from the group's recorded state when the edit happens, never from the delivery that
triggered it. A retried or late delivery then cannot put an older state back on the root.
"""

from datetime import datetime

from products.alerts_platform.backend.delivery.message import state_symbol
from products.alerts_platform.backend.facade.contracts import AlertEventKind, PlatformAlertSnapshot
from products.alerts_platform.backend.facade.enums import PlatformAlertState


def state_line(snapshot: PlatformAlertSnapshot | None, *, episode_started_at: datetime, as_of: datetime) -> str | None:
    """The line for the firing that opened this thread, or None when no line is certain.

    None leaves the root as it is. That covers a group with no recorded state, and an errored,
    broken or snoozed group, which is a different conversation from the firing this root opened.
    """
    if snapshot is None:
        return None
    when = as_of.strftime("%H:%M UTC")
    # The lifecycle keeps `firing_started_at` only while its firing is open, so equality means
    # the firing this root announced has not ended.
    episode_open = snapshot.firing_started_at == episode_started_at
    if episode_open and snapshot.state == PlatformAlertState.FIRING:
        return f"{state_symbol(AlertEventKind.FIRING)} Still firing as of {when}"
    # Shown only for the two states a reader of a firing expects. A later firing has its own root,
    # so this one reads as resolved even while the group fires again.
    if not episode_open and snapshot.state in (PlatformAlertState.NOT_FIRING, PlatformAlertState.FIRING):
        return f"{state_symbol(AlertEventKind.RESOLVED)} Resolved as of {when}"
    return None
