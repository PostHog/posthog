from collections.abc import Mapping
from typing import Any

from rest_framework import serializers

from products.dashboards.backend.constants import MAX_GROUP_KEY_LENGTH, MAX_GROUPS
from products.dashboards.backend.models.dashboard import DASHBOARD_GRID_COMPACTION_MODES, DASHBOARD_GRID_SPACING_GAPS
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


def stored_customization(customization: Any) -> dict[str, Any]:
    customization = normalize_dashboard_customization(customization)
    tile_spacing = customization.get("tile_spacing")
    layout_compaction = customization.get("layout_compaction")
    stored: dict[str, Any] = {}
    if isinstance(tile_spacing, str) and tile_spacing in DASHBOARD_GRID_SPACING_GAPS:
        stored["tile_spacing"] = tile_spacing
    if isinstance(layout_compaction, str) and layout_compaction in DASHBOARD_GRID_COMPACTION_MODES:
        stored["layout_compaction"] = layout_compaction
    groups = stored_groups(customization)
    if groups:
        stored["groups"] = groups
    return stored


def template_customization(customization: Any) -> dict[str, Any]:
    # A dashboard rejects group writes past these limits, so a template must not create one that breaks them.
    stored = stored_customization(customization)
    groups = [(key, group) for key, group in stored.pop("groups", {}).items() if len(key) <= MAX_GROUP_KEY_LENGTH]
    if groups:
        stored["groups"] = dict(groups[:MAX_GROUPS])
    return stored
