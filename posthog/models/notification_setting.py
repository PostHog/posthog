from enum import Enum
from typing import Literal, Optional

from posthog.models import User


class NotificationSetting(Enum):
    WEEKLY_PROJECT_DIGEST = "weekly_project_digest"
    PLUGIN_DISABLED = "plugin_disabled"


NotificationSettingType = Literal["weekly_project_digest", "plugin_disabled"]


def should_send_notification(
    user: User,
    notification_type: NotificationSettingType,
    team_id: Optional[int] = None,
) -> bool:
    """
    Determines if a notification should be sent to a user based on their notification settings.

    Args:
        user: The user to check settings for
        notification_type: The type of notification being sent. It must be the enum member's value!
        team_id: Optional team ID for team-specific notifications

    Returns:
        bool: True if the notification should be sent, False otherwise
    """
    settings = user.notification_settings

    if notification_type == NotificationSetting.WEEKLY_PROJECT_DIGEST.value:
        # First check global digest setting
        if settings.get("all_weekly_digest_disabled", False):
            return False

        # Then check project-specific setting if team_id provided
        if team_id is not None:
            project_settings = settings.get("project_weekly_digest_disabled", {})
            return not project_settings.get(str(team_id), False)

        return True

    elif notification_type == NotificationSetting.PLUGIN_DISABLED.value:
        return not settings.get("plugin_disabled", True)  # Default to True (disabled) if not set

    # The below typeerror is ignored because we're currently handling the notification
    # types above, so technically it's unreachable. However if another is added but
    # not handled in this function, we want this as a fallback.
    return True  # type: ignore
