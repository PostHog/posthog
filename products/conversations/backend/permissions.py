from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from posthog.models.user import User

from products.conversations.backend.github_integration_helpers import user_is_conversations_admin


class IsConversationsAdmin(BasePermission):
    message = "Only organization admins can manage conversation channels."

    def has_permission(self, request: Request, view) -> bool:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return False
        return user_is_conversations_admin(user, user.current_team.organization_id)
