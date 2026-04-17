from rest_framework.permissions import BasePermission
from rest_framework.request import Request


class GuestAccessPermission(BasePermission):
    """
    Hard-gates which viewset actions a guest user may invoke.
    Viewsets must explicitly opt in by declaring `guest_enabled_actions: list[str]` (empty by default).
    Mirrors the sharing-token opt-in pattern (`sharing_enabled_actions` + `SharingTokenPermission`).
    Non-guest users bypass this permission entirely.
    """

    message = "This action is not available to guest users."

    def has_permission(self, request: Request, view) -> bool:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return True
        if not user.organization_memberships.filter(is_guest=True).exists():
            return True
        guest_enabled_actions = getattr(view, "guest_enabled_actions", None)
        if not guest_enabled_actions:
            return False
        return getattr(view, "action", None) in guest_enabled_actions
