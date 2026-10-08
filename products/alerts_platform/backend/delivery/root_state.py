"""The current-state line an edited root message shows.

Read from the group's `PlatformAlert` row when the edit happens, never from the delivery that
triggered it. A retried or late delivery then cannot put an older state back on the root.
"""

from datetime import datetime

from django.utils import timezone

from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.alerts_platform.backend.models import PlatformAlert


def current_state_line(
    *, team_id: int, configuration_id: str, grouping_key: str, episode_started_at: datetime
) -> str | None:
    """The line for the firing that opened this thread, or None when no line is certain.

    None leaves the root as it is. That covers a group with no row, and an errored, broken or
    snoozed check, which is a different conversation from the firing this root opened.
    """
    alert = (
        PlatformAlert.objects.for_team(team_id)
        .filter(configuration_id=configuration_id, grouping_key=grouping_key)
        .only("state", "firing_started_at")
        .first()
    )
    if alert is None:
        return None
    as_of = timezone.now().strftime("%H:%M UTC")
    still_this_firing = alert.state == PlatformAlertState.FIRING and alert.firing_started_at == episode_started_at
    if still_this_firing:
        return f"\U0001f534 Still firing as of {as_of}"
    # A later firing has its own root, so this one is over even while the group fires again.
    if alert.state in (PlatformAlertState.NOT_FIRING, PlatformAlertState.FIRING):
        return f"\U0001f7e2 Resolved as of {as_of}"
    return None
