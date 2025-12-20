from dataclasses import dataclass


@dataclass
class PolicyDecision:
    """Result of policy evaluation"""

    result: str
    reason: str
    message: str
    approvers: dict
    policy_snapshot: dict


class PolicyEngine:
    """Evaluates approval policies"""

    def get_policy(self, action_key: str, team, organization):
        """
        Get the active policy for an action.

        Lookup order:
        1. Team-level policy (if team provided)
        2. Org-level policy
        """
        from posthog.approvals.models import ApprovalPolicy

        policy = None

        if team:
            policy = (
                ApprovalPolicy.objects.enabled()
                .filter(
                    action_key=action_key,
                    organization=organization,
                    team=team,
                )
                .first()
            )

        if not policy:
            policy = (
                ApprovalPolicy.objects.enabled()
                .filter(
                    action_key=action_key,
                    organization=organization,
                    team__isnull=True,
                )
                .first()
            )

        return policy

    def evaluate(self, policy, actor, intent: dict, context: dict) -> PolicyDecision:
        """
        Evaluate if an action requires approval.

        Returns PolicyDecision with:
        - ALLOW: User can execute immediately (bypass role)
        - DENY: Action not allowed
        - REQUIRE_APPROVAL: Must get approvals
        """
        if self._has_bypass_role(actor, policy, context):
            return PolicyDecision(
                result="ALLOW",
                reason="User has bypass role",
                message="Approved immediately",
                approvers={},
                policy_snapshot={},
            )

        approver_config = policy.approver_config

        if not policy.allow_self_approve and self._actor_is_approver(actor, approver_config, context):
            message = "A change request has been created and is pending approval from others."
        else:
            message = "A change request has been created and is pending approval."

        return PolicyDecision(
            result="REQUIRE_APPROVAL",
            reason="Policy matched",
            message=message,
            approvers=approver_config,
            policy_snapshot={
                "quorum": approver_config["quorum"],
                "users": approver_config.get("users", []),
                "roles": approver_config.get("roles", []),
                "allow_self_approve": policy.allow_self_approve,
            },
        )

    def _has_bypass_role(self, actor, policy, context: dict) -> bool:
        """Check if user has a bypass role"""
        if not policy.bypass_roles:
            return False

        org = context.get("organization")
        if org:
            membership = actor.organization_memberships.filter(organization=org).first()
            if membership and str(membership.level) in policy.bypass_roles:
                return True

        return False

    def _actor_is_approver(self, actor, approver_config: dict, context: dict) -> bool:
        """
        Check if actor is in the approver set.

        Supports both:
        - Direct users: {"users": [42, 99]}
        - Roles: {"roles": ["uuid-1", "uuid-2"]}

        Returns True if actor matches either users OR roles.
        """
        # Check direct user IDs
        if "users" in approver_config and actor.id in approver_config["users"]:
            return True

        # Check role membership
        if approver_config.get("roles"):
            try:
                from ee.models.rbac.role import RoleMembership
            except ImportError:
                return False

            org = context.get("organization")
            if not org:
                return False

            actor_roles = set(
                RoleMembership.objects.filter(user=actor, role__organization=org).values_list("role_id", flat=True)
            )

            approver_roles = set(approver_config["roles"])
            if actor_roles & approver_roles:
                return True

        return False
