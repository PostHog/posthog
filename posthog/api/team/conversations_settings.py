"""Conversations settings update helpers."""

import secrets
from typing import Any

from django.db import transaction

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.event_usage import report_user_action
from posthog.models import Team, User


@extend_schema_field(OpenApiTypes.OBJECT)
class ConversationsSettingsField(serializers.JSONField):
    pass


MANAGED_CONVERSATIONS_SETTINGS = (
    # Strip widget_public_token from user input - it's auto-generated only
    "widget_public_token",
    # Integration state is managed only by dedicated endpoints, not user input
    "slack_bot_token",
    "slack_team_id",
    "slack_enabled",
    "slack_scopes",
    "email_enabled",
    "teams_enabled",
    "teams_tenant_id",
    "teams_team_id",
    "teams_team_name",
    "teams_channel_id",
    "teams_channel_name",
    "teams_channels",
    "github_enabled",
    "github_integration_id",
    "github_repos",
)

LOCKED_CONVERSATIONS_COLUMNS = ("conversations_settings", "conversations_enabled")


def strip_managed_conversations_settings(value: dict[str, Any]) -> None:
    if not isinstance(value, dict):
        raise serializers.ValidationError("Conversation settings must be an object or null.")
    for managed_key in MANAGED_CONVERSATIONS_SETTINGS:
        value.pop(managed_key, None)


def merge_conversations_settings(value: dict[str, Any] | None, existing: object) -> dict[str, Any] | None:
    existing = conversations_settings_as_dict(existing)
    if value is None:
        return {key: existing[key] for key in MANAGED_CONVERSATIONS_SETTINGS if key in existing} or None
    return {**existing, **value}


def merge_conversations_settings_locked(
    team: Team,
    validated_data: dict[str, Any],
    patch_conversations_settings: bool,
    other_update_fields: list[str],
) -> dict[str, Any]:
    """Merge the conversations columns this request writes under one lock on the team row.

    Shared by the team and project serializers — both endpoints can PATCH the settings.
    The merge reads and the save must share one locked view of the team row: a dedicated
    integration update (Slack/Teams OAuth, support token rotation) commits whole-blob
    conversations_settings writes too, and a merge built on the pre-request snapshot would
    silently restore the state that update had just replaced. Keyed on the columns this
    request writes, not on which key the client sent: the token handler can inject
    conversations_settings into a payload that only sent conversations_enabled.
    The same save writes other_update_fields, which the caller already set on the team, so a
    PATCH that mixes conversation and other fields saves the row once and commits all or nothing.
    Returns the locked row's pre-merge conversations_settings and conversations_enabled,
    so the caller can correct its before-snapshot: that snapshot was taken before this
    lock re-read the row, and a concurrent integration write in between would otherwise
    get attributed to this request in the activity log and the settings-changed event.
    """
    with transaction.atomic():
        locked_team = (
            Team.objects.select_for_update(no_key=True)
            .only("conversations_settings", "conversations_enabled")
            .get(pk=team.pk)
        )
        if patch_conversations_settings:
            validated_data["conversations_settings"] = merge_conversations_settings(
                validated_data["conversations_settings"], locked_team.conversations_settings
            )

        validated_data = handle_conversations_token_on_update(
            validated_data, locked_team.conversations_enabled, locked_team.conversations_settings
        )
        team.conversations_settings = validated_data.get("conversations_settings", locked_team.conversations_settings)
        # Sync the flag even when this request does not write it. Otherwise the caller's
        # after-snapshot keeps a stale value and a concurrent toggle is logged as this user's.
        team.conversations_enabled = validated_data.get("conversations_enabled", locked_team.conversations_enabled)
        update_fields = ["conversations_settings", *other_update_fields, "updated_at"]
        if "conversations_enabled" in validated_data:
            update_fields.append("conversations_enabled")
        team.save(update_fields=update_fields)
        for column in LOCKED_CONVERSATIONS_COLUMNS:
            validated_data.pop(column, None)

    return {
        "conversations_settings": locked_team.conversations_settings,
        "conversations_enabled": locked_team.conversations_enabled,
    }


def conversations_settings_as_dict(value: object) -> dict[str, Any]:
    """Coerce a conversations_settings value to a dict for merging or diffing.

    A row written before validation required an object/null can hold a stray array or scalar;
    treat it as empty rather than raising.
    """
    return value if isinstance(value, dict) else {}


def report_conversations_settings_changes(
    user: User, before_settings: dict | None, after_settings: dict | None, team: Team
) -> None:
    """Fire one "support setting changed" event per changed conversations_settings key.

    Shared by the team and project serializers — both endpoints can PATCH the settings.
    Pass the settings this request wrote, not the refreshed row: a write that commits
    after this request's write would otherwise be reported as this user's change.
    """
    old_settings = conversations_settings_as_dict(before_settings)
    new_settings = conversations_settings_as_dict(after_settings)
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
    current_conversations_settings: object,
) -> dict[str, Any]:
    """Auto-generate/clear conversations widget token based on conversations_enabled changes."""
    if "conversations_enabled" not in validated_data:
        return validated_data

    is_enabling = validated_data["conversations_enabled"] and not current_conversations_enabled
    is_disabling = not validated_data["conversations_enabled"] and current_conversations_enabled

    stored_settings = conversations_settings_as_dict(current_conversations_settings)

    if is_enabling:
        # Check if token already exists in current DB state (not user input, which is stripped)
        has_token = stored_settings.get("widget_public_token")
        if not has_token:
            conv_settings = dict(validated_data.get("conversations_settings", stored_settings) or {})
            conv_settings["widget_public_token"] = secrets.token_urlsafe(32)
            validated_data["conversations_settings"] = conv_settings
    elif is_disabling:
        conv_settings = dict(validated_data.get("conversations_settings", stored_settings) or {})
        conv_settings["widget_public_token"] = None
        validated_data["conversations_settings"] = conv_settings

    return validated_data
