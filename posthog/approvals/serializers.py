from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.approvals.models import Approval, ApprovalPolicy, ChangeRequest


class ChangeRequestSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    applied_by = UserBasicSerializer(read_only=True)
    approvals = serializers.SerializerMethodField()
    can_approve = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    is_requester = serializers.SerializerMethodField()
    user_decision = serializers.SerializerMethodField()

    class Meta:
        model = ChangeRequest
        fields = [
            "id",
            "action_key",
            "action_version",
            "resource_type",
            "resource_id",
            "intent",
            "intent_display",
            "policy_snapshot",
            "validation_status",
            "validation_errors",
            "validated_at",
            "state",
            "created_by",
            "applied_by",
            "created_at",
            "updated_at",
            "expires_at",
            "applied_at",
            "apply_error",
            "result_data",
            "approvals",
            "can_approve",
            "can_cancel",
            "is_requester",
            "user_decision",
        ]
        read_only_fields = [
            "id",
            "action_key",
            "action_version",
            "resource_type",
            "resource_id",
            "intent",
            "intent_display",
            "policy_snapshot",
            "validation_status",
            "validation_errors",
            "validated_at",
            "state",
            "created_by",
            "applied_by",
            "created_at",
            "updated_at",
            "expires_at",
            "applied_at",
            "apply_error",
            "result_data",
        ]

    def get_approvals(self, obj):
        approvals = obj.approvals.all()
        return ApprovalSerializer(approvals, many=True).data

    def get_can_approve(self, obj: ChangeRequest) -> bool:
        """Check if current user can approve this change request."""
        request = self.context.get("request")
        if not request or not request.user:
            return False

        user = request.user
        policy = obj.policy_snapshot

        # If user is the requester and self-approve is not allowed, they cannot approve
        is_requester = obj.created_by_id == user.id
        allow_self_approve = policy.get("allow_self_approve", False)
        if is_requester and not allow_self_approve:
            return False

        # Check if user is in approver users list
        approver_users = policy.get("users", [])
        if user.id in approver_users:
            return True

        # Check if user has any of the required roles
        approver_roles = policy.get("roles", [])
        if approver_roles:
            try:
                from ee.models.rbac.role import RoleMembership

                user_role_ids = set(
                    RoleMembership.objects.filter(
                        user=user,
                        role__organization=obj.organization,
                    ).values_list("role_id", flat=True)
                )

                if user_role_ids & set(approver_roles):
                    return True
            except ImportError:
                pass

        return False

    def get_can_cancel(self, obj: ChangeRequest) -> bool:
        """Check if current user can cancel this change request."""
        from posthog.approvals.models import ChangeRequestState

        request = self.context.get("request")
        if not request or not request.user:
            return False

        # Only the requester can cancel, and only if it's still pending
        return obj.created_by_id == request.user.id and obj.state == ChangeRequestState.PENDING

    def get_is_requester(self, obj: ChangeRequest) -> bool:
        """Check if current user is the requester."""
        request = self.context.get("request")
        if not request or not request.user:
            return False

        return obj.created_by_id == request.user.id

    def get_user_decision(self, obj: ChangeRequest) -> str | None:
        """Get the current user's approval decision if they have voted."""
        request = self.context.get("request")
        if not request or not request.user:
            return None

        user_approval = obj.approvals.filter(created_by_id=request.user.id).first()
        if user_approval:
            return user_approval.decision

        return None


class ApprovalSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Approval
        fields = [
            "id",
            "created_by",
            "decision",
            "reason",
            "created_at",
        ]
        read_only_fields = ["id", "created_by", "created_at"]


class BypassRolesField(serializers.ListField):
    child = serializers.UUIDField()

    def to_representation(self, value):
        return [str(role.id) for role in value.all()]


class ApprovalPolicySerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    bypass_roles = BypassRolesField(required=False, default=list)

    class Meta:
        model = ApprovalPolicy
        fields = [
            "id",
            "action_key",
            "conditions",
            "approver_config",
            "allow_self_approve",
            "bypass_org_membership_levels",
            "bypass_roles",
            "expires_after",
            "enabled",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def validate_bypass_roles(self, value):
        if not value:
            return value

        try:
            from ee.models.rbac.role import Role
        except ImportError:
            raise serializers.ValidationError("RBAC roles are not available")

        if self.instance:
            # Update: get organization from existing policy
            organization_id = self.instance.organization_id
        else:
            # Create: get organization from view
            organization_id = self.context["view"].organization.id

        roles = Role.objects.filter(id__in=value)

        # Check all submitted IDs exist
        found_ids = {str(r.id) for r in roles}
        submitted_ids = {str(v) for v in value}
        missing_ids = submitted_ids - found_ids
        if missing_ids:
            raise serializers.ValidationError(f"Roles do not exist: {', '.join(missing_ids)}")

        # Check all roles belong to the correct organization
        invalid_roles = [r for r in roles if r.organization_id != organization_id]
        if invalid_roles:
            invalid_names = [r.name for r in invalid_roles]
            raise serializers.ValidationError(f"Roles must belong to the same organization: {', '.join(invalid_names)}")

        return value

    def create(self, validated_data):
        bypass_role_ids = validated_data.pop("bypass_roles", [])
        instance = super().create(validated_data)
        if bypass_role_ids:
            instance.set_bypass_roles([str(rid) for rid in bypass_role_ids])
        return instance

    def update(self, instance, validated_data):
        bypass_role_ids = validated_data.pop("bypass_roles", None)
        instance = super().update(instance, validated_data)
        if bypass_role_ids is not None:
            instance.set_bypass_roles([str(rid) for rid in bypass_role_ids])
        return instance
