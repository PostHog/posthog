from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.rbac.user_access_control import AccessControlLevel
    from posthog.scopes import APIScopeObject


def field_access_control(field, resource: "APIScopeObject", level: "AccessControlLevel"):
    """
    Helper function for creating access-controlled fields.

    Usage:
        class MyModel(models.Model):
            session_recording_opt_in = field_access_control(
                models.BooleanField(default=False),
                "session_recording",
                "editor"
            )
    """
    field._access_control_resource = resource
    field._access_control_level = level
    return field
