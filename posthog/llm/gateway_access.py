from typing import TYPE_CHECKING

from rest_framework.exceptions import PermissionDenied

from posthog.exceptions_capture import capture_exception

if TYPE_CHECKING:
    from posthog.models.user import User


class GatewayAccessBlocked(PermissionDenied):
    default_code = "provisioned_account_gateway_disabled"
    default_detail = "Use the installation skill with your own coding agent to set up this account."


def require_gateway_access(user: "User") -> None:
    if user.llm_gateway_access_blocked:
        error = GatewayAccessBlocked()
        capture_exception(error, {"user_id": user.pk})
        raise error
