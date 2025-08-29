from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.rbac.user_access_control import AccessControlLevel
    from posthog.scopes import APIScopeObject


def field_access_control(resource: "APIScopeObject", level: "AccessControlLevel"):
    """
    Decorator to specify field-level access control requirements.

    Usage:
        class MyModel(models.Model):
            session_recording_opt_in = field_access_control("session_recording", "editor")(
                models.BooleanField(default=False)
            )
    """

    def decorator(field):
        # Add access control metadata to the field
        field._access_control_resource = resource
        field._access_control_level = level
        return field

    return decorator
