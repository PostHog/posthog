"""Conversations settings update helpers."""

import secrets
from typing import Any

from posthog.event_usage import report_user_action
from posthog.models import Team, User


def report_conversations_settings_changes(user: User, before_settings: dict | None, team: Team) -> None:
    """Fire one "support setting changed" event per changed conversations_settings key.

    Shared by the team and project serializers — both endpoints can PATCH the settings.
    """
    old_settings = before_settings or {}
    new_settings = team.conversations_settings or {}
    changed_keys = sorted(
        k for k in old_settings.keys() | new_settings.keys() if old_settings.get(k) != new_settings.get(k)
    )
    # One event per changed setting so insights can break down by `setting`.
    for key in changed_keys:
        new_value = new_settings.get(key)
        properties: dict[str, Any] = {"setting": key}
        # Only non-string values are safe to report — the dict holds free text and the widget token.
        if isinstance(new_value, (bool, int, float, type(None))):
            properties["value"] = new_value
        report_user_action(user, "support setting changed", properties, team=team)


def handle_conversations_token_on_update(
    validated_data: dict[str, Any],
    current_conversations_enabled: bool | None,
    current_conversations_settings: dict | None,
) -> dict[str, Any]:
    """Auto-generate/clear conversations widget token based on conversations_enabled changes."""
    if "conversations_enabled" not in validated_data:
        return validated_data

    is_enabling = validated_data["conversations_enabled"] and not current_conversations_enabled
    is_disabling = not validated_data["conversations_enabled"] and current_conversations_enabled

    if is_enabling:
        # Check if token already exists in current DB state (not user input, which is stripped)
        has_token = current_conversations_settings and current_conversations_settings.get("widget_public_token")
        if not has_token:
            conv_settings = dict(validated_data.get("conversations_settings") or current_conversations_settings or {})
            conv_settings["widget_public_token"] = secrets.token_urlsafe(32)
            validated_data["conversations_settings"] = conv_settings
    elif is_disabling:
        conv_settings = dict(validated_data.get("conversations_settings") or current_conversations_settings or {})
        conv_settings["widget_public_token"] = None
        validated_data["conversations_settings"] = conv_settings

    return validated_data
