"""Conversations settings update helpers."""

import secrets
from typing import Any

from django.db import transaction

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.api.utils import validate_authorized_url_wildcards
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


VALID_CONVERSATIONS_CHANNELS = {"widget", "email", "slack", "teams", "github"}
VALID_AI_REPLY_MODES = {"private_note", "bot_reply"}
VALID_AI_REPLY_TICKET_TYPES = {"how_to", "diagnostic", "account_billing"}
# Only how_to replies may be published to the ticket author. diagnostic/account_billing
# draw on project data (events, persons, recordings, logs) and must stay private notes —
# there's no per-author authorization that the customer is entitled to that data.
BOT_REPLY_TICKET_TYPES = {"how_to"}


def validate_conversations_settings(
    value: dict[str, Any], existing: dict[str, Any] | None, team_id: int | None
) -> dict[str, Any]:
    """Run every check a conversations_settings write must pass, shared by the team and project serializers.

    `existing` is the team's currently stored conversations_settings (or None), used to skip
    unchanged values and for merge-aware playbook validation. `team_id` is the team whose AI context gets validated.
    """
    strip_managed_conversations_settings(value)
    # The web app sends back every stored setting on each save. A value stored before a check
    # existed must not block an unrelated save or get cut down, so only changed values get checked.
    stored = existing or {}
    unchanged = {key: item for key, item in value.items() if key in stored and stored[key] == item}
    for key in unchanged:
        del value[key]
    # Filter out None values from widget_domains if present
    if "widget_domains" in value and value["widget_domains"] is not None:
        value["widget_domains"] = [domain for domain in value["widget_domains"] if domain]
        validate_authorized_url_wildcards(value["widget_domains"])
    # Normalize multi-channel list: must be a list of non-empty strings, deduped, capped at 50
    if "slack_channel_ids" in value:
        raw = value.get("slack_channel_ids")
        if isinstance(raw, list):
            cleaned: list[str] = []
            seen: set[str] = set()
            for item in raw:
                if isinstance(item, str) and item and item not in seen:
                    seen.add(item)
                    cleaned.append(item)
            value["slack_channel_ids"] = cleaned[:50]
        elif raw is not None:
            # Drop a malformed value instead of rejecting the save, but keep an explicit
            # null so a clearing PATCH still overwrites the stored list (see
            # merge_conversations_settings, which only replaces keys present here).
            value.pop("slack_channel_ids", None)
    icon_url = value.get("slack_bot_icon_url")
    if icon_url is not None:
        if not isinstance(icon_url, str):
            raise serializers.ValidationError({"slack_bot_icon_url": "Must be a string."})
        icon_url = icon_url.strip()
        value["slack_bot_icon_url"] = icon_url or None
        if icon_url and not icon_url.startswith("https://"):
            raise serializers.ValidationError({"slack_bot_icon_url": "Must be an HTTPS URL."})
    display_name = value.get("slack_bot_display_name")
    if display_name is not None:
        if not isinstance(display_name, str):
            raise serializers.ValidationError({"slack_bot_display_name": "Must be a string."})
        display_name = display_name.strip()
        value["slack_bot_display_name"] = display_name or None
        if display_name and (len(display_name) > 200 or any(ord(c) < 32 for c in display_name)):
            raise serializers.ValidationError(
                {"slack_bot_display_name": "Must be 200 characters or fewer with no control characters."}
            )
    for toggle_key in ("slack_notify_on_join", "slack_notify_on_leave", "slack_nudge_enabled"):
        if toggle_key in value:
            value[toggle_key] = bool(value[toggle_key])
    if "slack_alert_channel_id" in value:
        alert_channel = value.get("slack_alert_channel_id")
        if alert_channel is None:
            value["slack_alert_channel_id"] = None
        elif isinstance(alert_channel, str):
            value["slack_alert_channel_id"] = alert_channel.strip() or None
        else:
            raise serializers.ValidationError({"slack_alert_channel_id": "Must be a string."})
    # AI resolution channels: list of valid channel strings or null
    if "ai_resolution_channels" in value:
        channels = value.get("ai_resolution_channels")
        if channels is None:
            pass
        elif isinstance(channels, list):
            invalid = [c for c in channels if not isinstance(c, str) or c not in VALID_CONVERSATIONS_CHANNELS]
            if invalid:
                raise serializers.ValidationError(
                    {
                        "ai_resolution_channels": f"Invalid channel(s): {', '.join(str(c) for c in invalid)}. "
                        f"Valid options: {', '.join(sorted(VALID_CONVERSATIONS_CHANNELS))}."
                    }
                )
            value["ai_resolution_channels"] = channels
        else:
            raise serializers.ValidationError({"ai_resolution_channels": "Must be a list of channel names or null."})
    # AI reply modes: { channel: { ticket_type: mode } } or null
    if "ai_reply_modes" in value:
        modes = value.get("ai_reply_modes")
        if modes is None:
            pass
        elif isinstance(modes, dict):
            cleaned_modes: dict[str, dict[str, str]] = {}
            for ch, type_map in modes.items():
                if ch not in VALID_CONVERSATIONS_CHANNELS or not isinstance(type_map, dict):
                    continue
                cleaned_map: dict[str, str] = {}
                for tt, mode in type_map.items():
                    if (
                        tt not in VALID_AI_REPLY_TICKET_TYPES
                        or not isinstance(mode, str)
                        or mode not in VALID_AI_REPLY_MODES
                    ):
                        continue
                    # Demote bot_reply to private_note for ticket types that may never be
                    # published (diagnostic/account_billing). Coerce rather than reject so a
                    # stale value doesn't block unrelated settings saves.
                    if mode == "bot_reply" and tt not in BOT_REPLY_TICKET_TYPES:
                        mode = "private_note"
                    cleaned_map[tt] = mode
                if cleaned_map:
                    cleaned_modes[ch] = cleaned_map
            value["ai_reply_modes"] = cleaned_modes
        else:
            raise serializers.ValidationError({"ai_reply_modes": "Must be an object or null."})
    from products.conversations.backend.api.ai_context import validate_ai_context_conversations_settings
    from products.conversations.backend.api.ai_reply_playbook import validate_playbook_conversations_settings

    validate_playbook_conversations_settings(value, existing=existing)
    validate_ai_context_conversations_settings(value, team_id=team_id)
    value.update(unchanged)
    return value
