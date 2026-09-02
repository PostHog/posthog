from collections.abc import Callable
from typing import Any


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
    from posthog.models.user import User

    current_settings = user.partial_notification_settings or {}
    if setting_key in current_settings:
        return False

    if not team_data:
        return False

    busiest_team_id = max(team_data, key=lambda tid: sort_key(team_data[tid]))
    current_settings[setting_key] = {str(busiest_team_id): True}
    if not persist:
        user.partial_notification_settings = current_settings
        return False

    User.objects.filter(pk=user.pk).update(partial_notification_settings=current_settings)
    return True


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
