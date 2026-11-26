"""
Dashboard display settings: the tile groups and layout choices a dashboard stores in its
`customization`, and the dashboard a team's Home tab shows.

The validators raise `DashboardCustomizationRejected`. The caller decides which HTTP response it
becomes; the dashboard API answers 400 on the error's field.
"""

from collections.abc import Mapping

from pydantic import JsonValue

from products.dashboards.backend import customization as customization_logic
from products.dashboards.backend.logic import team_settings as team_settings_logic


def normalize_dashboard_customization(customization: JsonValue) -> dict[str, JsonValue]:
    """A copy of stored customization to change, or an empty dict when the stored value is not an object."""
    return customization_logic.normalize_dashboard_customization(customization)


def stored_customization(customization: JsonValue) -> dict[str, JsonValue]:
    """The settings of stored customization that a dashboard shows: known layout choices and valid groups."""
    return customization_logic.stored_customization(customization)


def stored_groups(customization: JsonValue) -> dict[str, dict[str, JsonValue]]:
    """The valid groups of stored customization by normalized key, without the settings equal to their defaults.

    A title stored in the legacy `group_titles` wins over the title in `groups`.
    """
    return customization_logic.stored_groups(customization)


def without_default_settings(group: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """A group's settings without a blank title and without the settings equal to their defaults."""
    return customization_logic.without_default_settings(group)


def normalized_group_key(group_key: str) -> str:
    """The group key without surrounding whitespace.

    Raises `DashboardCustomizationRejected`, with no field, for a key with a null character.
    """
    return customization_logic.normalized_group_key(group_key)


def validated_group_key(group_key: JsonValue) -> str | None:
    """A tile's normalized group key, or None when the tile is in no group.

    Raises `DashboardCustomizationRejected` on `group_key` for a key that is not a string or null,
    is too long, or has a null character.
    """
    return customization_logic.validated_group_key(group_key)


def validated_group_keys(groups: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """The groups by normalized key, in their order.

    Raises `DashboardCustomizationRejected`, with no field, when there are too many groups or a key
    is blank, too long, has a null character or is used twice after normalization.
    """
    return customization_logic.validated_group_keys(groups)


def validate_template_groups(customization: JsonValue, tiles: JsonValue) -> None:
    """Reject template groups that a dashboard made from the template could not hold.

    Raises `DashboardCustomizationRejected` on `customization` for its group keys, or on `tiles`
    for a tile's group key.
    """
    customization_logic.validate_template_groups(customization, tiles)


def clear_home_tab_dashboard(*, team_id: int, dashboard_id: int) -> None:
    """Point the team's Home tab back at the built-in view when it shows this dashboard."""
    team_settings_logic.clear_home_tab_dashboard(team_id=team_id, dashboard_id=dashboard_id)


__all__ = [
    "clear_home_tab_dashboard",
    "normalize_dashboard_customization",
    "normalized_group_key",
    "stored_customization",
    "stored_groups",
    "validate_template_groups",
    "validated_group_key",
    "validated_group_keys",
    "without_default_settings",
]
