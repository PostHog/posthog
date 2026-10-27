from collections.abc import Collection, Mapping
from typing import Any

from rest_framework import serializers

from products.dashboards.backend.constants import MAX_GROUP_KEY_LENGTH, MAX_GROUPS
from products.dashboards.backend.models.dashboard import (
    DASHBOARD_GRID_COMPACTION_MODES,
    DASHBOARD_GRID_SPACING_GAPS,
    DASHBOARD_TILE_GROUP_DISPLAY_MODES,
)
from products.dashboards.backend.widget_specs.openapi import DASHBOARD_TILE_GROUP_DEFAULTS, DashboardTileGroupSerializer


def normalize_dashboard_customization(customization: Any) -> dict[str, Any]:
    return customization.copy() if isinstance(customization, dict) else {}


def normalized_group_key(group_key: str) -> str:
    group_key = group_key.strip()
    if "\x00" in group_key:
        raise serializers.ValidationError("Group keys can't contain null characters.")
    return group_key


def stored_group_key(group_key: Any) -> str | None:
    if not isinstance(group_key, str):
        return None
    try:
        group_key = normalized_group_key(group_key)
    except serializers.ValidationError:
        return None
    return group_key if group_key and len(group_key) <= MAX_GROUP_KEY_LENGTH else None


def validated_group_key(group_key: Any) -> str | None:
    if group_key is None:
        return None
    if not isinstance(group_key, str):
        raise serializers.ValidationError({"group_key": "Group key must be a string or null."})
    try:
        group_key = normalized_group_key(group_key)
    except serializers.ValidationError as error:
        raise serializers.ValidationError({"group_key": error.detail}) from error
    if len(group_key) > MAX_GROUP_KEY_LENGTH:
        raise serializers.ValidationError(
            {"group_key": f"Group key can have at most {MAX_GROUP_KEY_LENGTH} characters."}
        )
    return group_key or None


def validated_group_keys[T](value: dict[str, T]) -> dict[str, T]:
    if len(value) > MAX_GROUPS:
        raise serializers.ValidationError(f"A dashboard can have at most {MAX_GROUPS} groups.")
    normalized: dict[str, T] = {}
    for key, item in value.items():
        group_key = normalized_group_key(key)
        if not group_key:
            raise serializers.ValidationError("Group keys can't be empty.")
        if len(group_key) > MAX_GROUP_KEY_LENGTH:
            raise serializers.ValidationError(f"Group keys can have at most {MAX_GROUP_KEY_LENGTH} characters.")
        if group_key in normalized:
            raise serializers.ValidationError(f'Group key "{group_key}" is used more than once.')
        normalized[group_key] = item
    return normalized


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def validate_template_groups(customization: Any, tiles: Any) -> None:
    """Reject template groups that a dashboard made from the template could not hold."""
    customization = _dict_or_empty(customization)
    try:
        validated_group_keys(
            {**_dict_or_empty(customization.get("groups")), **_dict_or_empty(customization.get("group_titles"))}
        )
    except serializers.ValidationError as error:
        raise serializers.ValidationError({"customization": error.detail}) from error
    for tile in tiles if isinstance(tiles, list) else []:
        try:
            validated_group_key(_dict_or_empty(tile).get("group_key"))
        except serializers.ValidationError as error:
            detail = error.detail
            raise serializers.ValidationError(
                {"tiles": detail["group_key"] if isinstance(detail, dict) else detail}
            ) from error


_NO_DEFAULT = object()


def _is_stored_group_setting(field: str, setting: Any) -> bool:
    if field == "title":
        return bool(setting)
    return setting != DASHBOARD_TILE_GROUP_DEFAULTS.get(field, _NO_DEFAULT)


def without_default_settings(group: Mapping[str, Any]) -> dict[str, Any]:
    return {field: setting for field, setting in group.items() if _is_stored_group_setting(field, setting)}


def _sparse_group(group_settings: Any) -> dict[str, Any] | None:
    group = DashboardTileGroupSerializer(data=group_settings)
    if not group.is_valid():
        return None
    return without_default_settings(group.validated_data)


def stored_groups(customization: Any) -> dict[str, dict[str, Any]]:
    customization = normalize_dashboard_customization(customization)
    groups = customization.get("groups") if isinstance(customization.get("groups"), dict) else {}
    titles = customization.get("group_titles") if isinstance(customization.get("group_titles"), dict) else {}
    stored: dict[str, dict[str, Any]] = {}
    for raw_key in {**groups, **titles}:
        if not isinstance(raw_key, str):
            continue
        try:
            group_key = normalized_group_key(raw_key)
        except serializers.ValidationError:
            continue
        group = _sparse_group(groups.get(raw_key, {}))
        # Only a server from before `groups` writes `group_titles`, so a stored title there is the newer one.
        title = _sparse_group({"title": titles[raw_key]}) if raw_key in titles else None
        if group_key and (group is not None or title is not None):
            stored[group_key] = {**(group or {}), **(title or {})}
    return stored


_CHOICE_SETTINGS: dict[str, Collection[str]] = {
    "tile_spacing": DASHBOARD_GRID_SPACING_GAPS,
    "layout_compaction": DASHBOARD_GRID_COMPACTION_MODES,
    "group_display": DASHBOARD_TILE_GROUP_DISPLAY_MODES,
}


def stored_customization(customization: Any) -> dict[str, Any]:
    customization = normalize_dashboard_customization(customization)
    stored: dict[str, Any] = {
        setting: customization[setting]
        for setting, choices in _CHOICE_SETTINGS.items()
        if isinstance(customization.get(setting), str) and customization[setting] in choices
    }
    groups = stored_groups(customization)
    if groups:
        stored["groups"] = groups
    return stored
