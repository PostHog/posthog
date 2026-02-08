from rest_framework import permissions


class CanApprove(permissions.BasePermission):
    """
    Checks:
    1. User is in the approver set (from policy_snapshot)
    2. User is not the requester (if self-approval not allowed)
    """

    message = "You do not have permission to approve this change request"

    def has_object_permission(self, request, view, obj):
        from posthog.approvals.models import ChangeRequestState

        if obj.state != ChangeRequestState.PENDING:
            self.message = "Only pending change requests can be approved"
            return False

        policy_snapshot = obj.policy_snapshot
        allow_self_approve = policy_snapshot.get("allow_self_approve", False)
        is_requester = obj.created_by == request.user

        # Check self-approval first - if requester and not allowed, deny immediately
        if is_requester and not allow_self_approve:
            self.message = "You cannot approve your own change request"
            return False

        # Check if user is in explicit approver set (users/roles)
        if self._user_in_approver_set(request.user, policy_snapshot, obj):
            return True

        self.message = "You are not in the approver set for this change request"
        return False

    def _user_in_approver_set(self, user, policy_snapshot: dict, change_request) -> bool:
        # Check direct user IDs
        if "users" in policy_snapshot and user.id in policy_snapshot["users"]:
            return True

        # Check role membership
        approver_roles = policy_snapshot.get("roles", [])
        if approver_roles:
            try:
                from ee.models.rbac.role import RoleMembership
            except ImportError:
                return False

            user_roles = set(
                RoleMembership.objects.filter(
                    user=user,
                    role__organization=change_request.organization,
                ).values_list("role_id", flat=True)
            )

            if user_roles & set(approver_roles):
                return True

        return False


class CanCancel(permissions.BasePermission):
    """
    Only the requester can cancel their own pending change request.
    """

    message = "You can only cancel your own change requests"

    def has_object_permission(self, request, view, obj):
        from posthog.approvals.models import ChangeRequestState

        if obj.state != ChangeRequestState.PENDING:
            self.message = "Only pending change requests can be canceled"
            return False

        if obj.created_by != request.user:
            self.message = "You can only cancel your own change requests"
            return False

        return True
