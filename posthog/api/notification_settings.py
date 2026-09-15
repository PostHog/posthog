import re
from collections.abc import Mapping
from typing import Any, cast

from rest_framework import serializers

from posthog.models import User
from posthog.models.organization_notification_lock import GovernedSetting, notification_locks_for_users
from posthog.models.user import NOTIFICATION_DEFAULTS, Notifications

from products.notifications.backend.facade.api import NotificationType

_VALID_NOTIFICATION_TYPE_VALUES: frozenset[str] = frozenset(t.value for t in NotificationType)
MAX_PIPELINE_NOTIFICATIONS = 1000
_PIPELINE_ID_PATTERN = re.compile(r"^(?:hog_function|batch_export|plugin_config):[0-9a-zA-Z-]{1,128}$")


def _reject_locked_notification_settings(user: User, incoming: Notifications, current: Mapping[str, Any]) -> None:
    """Stop a member changing a setting their organization enforces.

    The settings page disables these controls, but the disabling has to be enforced here too, or
    the rule is only a suggestion to anyone using the API directly. Only a changed value is
    refused: the page submits the whole map on every save, so an untouched governed setting has
    to pass through.

    Deliberately not scoped to one organization: a value the member stores is the one every
    organization that has no rule of its own falls back to, so any single rule freezes it.
    """
    locks = notification_locks_for_users([user.id]).get(user.id, {})
    if not locks:
        return

    for key, value in incoming.items():
        if isinstance(value, dict):
            stored: dict = current.get(key) or {}
            blocked = [
                scope_id
                for scope_id, scoped_value in value.items()
                if GovernedSetting(setting=key, scope_id=str(scope_id)) in locks
                and stored.get(scope_id) != scoped_value
            ]
            if blocked:
                raise serializers.ValidationError(
                    f"{key} is set by your organization for {', '.join(sorted(blocked))} and cannot be changed here",
                    code="permission_denied",
                )
        elif GovernedSetting(setting=key, scope_id="") in locks and current.get(key) != value:
            raise serializers.ValidationError(
                f"{key} is set by your organization and cannot be changed here",
                code="permission_denied",
            )


def _validate_pipeline_notifications(incoming: dict, merged: dict) -> None:
    for pipeline_id in incoming:
        if not isinstance(pipeline_id, str) or not _PIPELINE_ID_PATTERN.match(pipeline_id):
            raise serializers.ValidationError(
                f"Invalid pipeline id: {pipeline_id!r}",
                code="invalid_input",
            )
    if len(merged) > MAX_PIPELINE_NOTIFICATIONS:
        raise serializers.ValidationError(
            f"pipeline_notifications_disabled cannot have more than {MAX_PIPELINE_NOTIFICATIONS} entries",
            code="invalid_input",
        )


def validate_notification_settings(instance: User, notification_settings: Notifications) -> Notifications:
    current_settings = {
        **NOTIFICATION_DEFAULTS,
        **(instance.partial_notification_settings or {}),
    }

    _reject_locked_notification_settings(instance, notification_settings, current_settings)

    dict_notification_keys = (
        "project_weekly_digest_disabled",
        "error_tracking_weekly_digest_project_enabled",
        "web_analytics_weekly_digest_project_enabled",
        "organization_member_join_email_disabled",
        "pipeline_notifications_disabled",
    )

    for key, value in notification_settings.items():
        if key not in Notifications.__annotations__:
            raise serializers.ValidationError(
                f"Key {key} is not valid as a key for notification settings",
                code="invalid_input",
            )

        expected_type = Notifications.__annotations__[key]

        if key in dict_notification_keys:
            if not isinstance(value, dict):
                raise serializers.ValidationError(
                    f"{key} must be a dictionary mapping IDs to boolean values",
                    code="invalid_input",
                )
            for _, disabled in value.items():
                if not isinstance(disabled, bool):
                    raise serializers.ValidationError(
                        f"Notification setting values must be boolean, got {type(disabled)} instead",
                        code="invalid_input",
                    )
            merged = {**current_settings.get(key, {}), **value}
            if key == "pipeline_notifications_disabled":
                _validate_pipeline_notifications(value, merged)
            current_settings[key] = merged
        elif key == "realtime_notifications_disabled":
            if not isinstance(value, dict):
                raise serializers.ValidationError(
                    "realtime_notifications_disabled must be a dict",
                    code="invalid_input",
                )
            for type_key, team_map in value.items():
                if type_key not in _VALID_NOTIFICATION_TYPE_VALUES:
                    raise serializers.ValidationError(
                        f"Unknown notification type {type_key}",
                        code="invalid_input",
                    )
                if not isinstance(team_map, dict):
                    raise serializers.ValidationError(
                        f"Per-type value for {type_key} must be a dict of team_id to bool",
                        code="invalid_input",
                    )
                for _team_id, disabled in team_map.items():
                    if not isinstance(disabled, bool):
                        raise serializers.ValidationError(
                            f"Disabled flag for {type_key} must be boolean, got {type(disabled)}",
                            code="invalid_input",
                        )
            existing = current_settings.get("realtime_notifications_disabled", {}) or {}
            realtime_merged: dict[str, dict[str, bool]] = {**existing}
            for type_key, team_map in value.items():
                realtime_merged[type_key] = {**(existing.get(type_key, {}) or {}), **team_map}
            current_settings["realtime_notifications_disabled"] = realtime_merged
        elif key == "data_pipeline_error_threshold":
            if not isinstance(value, (int, float)):
                raise serializers.ValidationError(
                    f"data_pipeline_error_threshold must be a number, got {type(value)} instead",
                    code="invalid_input",
                )
            if value < 0.0 or value > 1.0:
                raise serializers.ValidationError(
                    f"data_pipeline_error_threshold must be between 0.0 and 1.0, got {value}",
                    code="invalid_input",
                )
            current_settings[key] = float(value)
        else:
            # For non-dict settings, validate type directly
            if not isinstance(value, expected_type):
                raise serializers.ValidationError(
                    f"{value} is not a valid type for notification settings, should be {expected_type}",
                    code="invalid_input",
                )
            current_settings[key] = value

    return cast(Notifications, current_settings)
