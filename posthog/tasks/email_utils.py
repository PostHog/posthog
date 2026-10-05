from collections.abc import Callable
from typing import Any

from django.db import transaction


def persist_digest_project_selection(user: Any, setting_key: str, selection: dict[str, bool]) -> bool:
    """Store a digest's auto-selected project map without discarding other settings writes.

    Every save rewrites the whole notification settings column, so a read-modify-write from a copy
    the digest run loaded minutes ago drops everything written since — including the member's own
    choice on the settings page, which then reads as if it never saved. Re-read the row under a
    lock and leave a selection made in that window alone.

    Returns True only when this call wrote the selection. Either way the in-memory user ends up
    with the stored settings, so the caller can route on them without a refresh.
    """
    from posthog.models.user import User

    with transaction.atomic():
        # no_key, because posthog_user is a parent row: a plain FOR UPDATE would make every
        # unrelated insert that references this user wait on the lock.
        locked = User.objects.select_for_update(no_key=True).filter(pk=user.pk).first()
        if locked is None:
            return False

        stored = locked.partial_notification_settings or {}
        chosen_since = setting_key in stored
        if not chosen_since:
            stored[setting_key] = selection
            User.objects.filter(pk=user.pk).update(partial_notification_settings=stored)

    user.partial_notification_settings = stored
    return not chosen_since


def auto_select_digest_project(
    user: Any,
    team_data: dict[int, Any],
    setting_key: str,
    sort_key: Callable[[Any], float],
    persist: bool = True,
) -> bool:
    """Auto-select the busiest project for first-time digest users.

    Returns True if settings were written to the database (caller should refresh_from_db).
    ``persist=False`` applies the selection to the in-memory user only, so a simulated run does
    not consume the one-shot enrollment.
    """
    current_settings = user.partial_notification_settings or {}
    if setting_key in current_settings:
        return False

    if not team_data:
        return False

    busiest_team_id = max(team_data, key=lambda tid: sort_key(team_data[tid]))
    selection = {str(busiest_team_id): True}
    if not persist:
        user.partial_notification_settings = {**current_settings, setting_key: selection}
        return False

    return persist_digest_project_selection(user, setting_key, selection)


def compute_week_over_week_change(current: float, previous: float | None, higher_is_better: bool) -> dict | None:
    """Compute a week-over-week percentage change dict for use in email templates.

    Returns None when there's no meaningful comparison (no previous data or 0% change).
    """
    if previous is None or previous == 0:
        return None

    percent_change = ((current - previous) / previous) * 100
    rounded = round(abs(percent_change))
    if rounded == 0:
        return None

    is_increase = percent_change > 0
    direction = "Up" if is_increase else "Down"
    is_good = (is_increase and higher_is_better) or (not is_increase and not higher_is_better)
    color = "#2f7d4f" if is_good else "#a13232"

    return {
        "percent": rounded,
        "direction": direction,
        "color": color,
        "text": f"{direction} {rounded}%",
        "long_text": f"{direction} {rounded}% from previous week",
    }
