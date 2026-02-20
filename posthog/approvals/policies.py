from dataclasses import dataclass
from typing import Any


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

    COMPARISON_OPERATORS = {
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
    }

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

    def get_all_matching_policies(self, action_key: str, team, organization, intent: dict):
        """
        Get all active policies for an action that match the given intent.
        Used for conflict detection.
        """
        from posthog.approvals.models import ApprovalPolicy

        policies = []

        if team:
            team_policies = ApprovalPolicy.objects.enabled().filter(
                action_key=action_key,
                organization=organization,
                team=team,
            )
            for policy in team_policies:
                if self._evaluate_conditions(policy.conditions, intent):
                    policies.append(policy)

        org_policies = ApprovalPolicy.objects.enabled().filter(
            action_key=action_key,
            organization=organization,
            team__isnull=True,
        )
        for policy in org_policies:
            if self._evaluate_conditions(policy.conditions, intent):
                policies.append(policy)

        return policies

    def evaluate(self, policy, actor, intent: dict, context: dict) -> PolicyDecision:
        """
        Evaluate if an action requires approval.

        Returns PolicyDecision with:
        - ALLOW: User can execute immediately (bypass or conditions don't match)
        - DENY: Action not allowed
        - REQUIRE_APPROVAL: Must get approvals
        """
        bypass_role_ids = [str(r.id) for r in policy.bypass_roles.all()]

        if self._has_bypass(actor, policy, bypass_role_ids, context):
            return PolicyDecision(
                result="ALLOW",
                reason="User has bypass",
                message="Approved immediately",
                approvers={},
                policy_snapshot={},
            )

        if not self._evaluate_conditions(policy.conditions, intent):
            return PolicyDecision(
                result="ALLOW",
                reason="Conditions not matched",
                message="Change does not require approval",
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
                "conditions": policy.conditions or {},
                "bypass_org_membership_levels": policy.bypass_org_membership_levels,
                "bypass_roles": bypass_role_ids,
            },
        )

    def _evaluate_conditions(self, conditions: dict[str, Any], intent: dict) -> bool:
        """
        Evaluate policy conditions against the intent.

        Returns True if conditions match (gating applies), False otherwise.
        If conditions is empty/None, returns True (gate all changes for that action).

        Condition types:
        - before_after: Compare field values before and after change
        - change_amount: Compare delta between before/after values
        - any_change: Gate if the field changes at all
        """
        if not conditions:
            return True

        condition_type = conditions.get("type")

        if condition_type == "before_after":
            return self._evaluate_before_after(conditions, intent)
        elif condition_type == "change_amount":
            return self._evaluate_change_amount(conditions, intent)
        elif condition_type == "any_change":
            return self._evaluate_any_change(conditions, intent)

        return True

    def _evaluate_before_after(self, conditions: dict[str, Any], intent: dict) -> bool:
        """
        Evaluate before_after condition type.

        Structure: {"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 50}
        Compares the "after" value against the condition value using the operator.
        Checks ALL paths where the field appears, returns True if ANY match.
        """
        field = conditions.get("field")
        operator = conditions.get("operator")
        threshold = conditions.get("value")

        if not field or not operator or threshold is None:
            return True

        compare_fn = self.COMPARISON_OPERATORS.get(operator)
        if not compare_fn:
            return True

        gated_changes = intent.get("gated_changes", {})
        field_values = gated_changes.get(field, [])

        for item in field_values:
            after_value = item.get("value")
            if after_value is not None:
                try:
                    if compare_fn(after_value, threshold):
                        return True
                except (TypeError, ValueError):
                    pass

        return False

    def _evaluate_change_amount(self, conditions: dict[str, Any], intent: dict) -> bool:
        """
        Evaluate change_amount condition type.

        Structure: {"type": "change_amount", "field": "rollout_percentage", "operator": ">", "value": 10}
        Calculates delta = after_value - before_value and compares against threshold.
        Only valid for numeric field types.
        """
        field = conditions.get("field")
        operator = conditions.get("operator")
        threshold = conditions.get("value")

        if not field or not operator or threshold is None:
            return True

        compare_fn = self.COMPARISON_OPERATORS.get(operator)
        if not compare_fn:
            return True

        current_state = intent.get("current_state", {})
        gated_changes = intent.get("gated_changes", {})

        before_values = current_state.get(field, [])
        after_values = gated_changes.get(field, [])

        before_by_path = {v["path"]: v["value"] for v in before_values}
        after_by_path = {v["path"]: v["value"] for v in after_values}

        all_paths = set(before_by_path.keys()) | set(after_by_path.keys())

        for path in all_paths:
            before_val = before_by_path.get(path)
            after_val = after_by_path.get(path)

            if before_val is not None and after_val is not None:
                try:
                    delta = after_val - before_val
                    if compare_fn(delta, threshold):
                        return True
                except (TypeError, ValueError):
                    pass

        return False

    def _evaluate_any_change(self, conditions: dict[str, Any], intent: dict) -> bool:
        """
        Evaluate any_change condition type.

        Structure: {"type": "any_change", "field": "rollout_percentage"}
        Returns True if the field value differs between before and after.
        """
        field = conditions.get("field")

        if not field:
            return True

        current_state = intent.get("current_state", {})
        gated_changes = intent.get("gated_changes", {})

        before_values = current_state.get(field, [])
        after_values = gated_changes.get(field, [])

        before_by_path = {v["path"]: v["value"] for v in before_values}
        after_by_path = {v["path"]: v["value"] for v in after_values}

        all_paths = set(before_by_path.keys()) | set(after_by_path.keys())

        for path in all_paths:
            before_val = before_by_path.get(path)
            after_val = after_by_path.get(path)
            if before_val != after_val:
                return True

        return False

    def _has_bypass(self, actor, policy, bypass_role_ids: list[str], context: dict) -> bool:
        """Check if user can bypass this policy based on org membership level or RBAC role."""
        org = context.get("organization")
        if not org:
            return False

        # Check bypass_org_membership_levels
        if policy.bypass_org_membership_levels:
            membership = actor.organization_memberships.filter(organization=org).first()
            if membership and str(membership.level) in policy.bypass_org_membership_levels:
                return True

        # Check bypass_roles (RBAC roles)
        if bypass_role_ids:
            try:
                from ee.models.rbac.role import RoleMembership
            except ImportError:
                pass
            else:
                user_role_ids = {
                    str(rid)
                    for rid in RoleMembership.objects.filter(
                        user=actor,
                        role__organization=org,
                    ).values_list("role_id", flat=True)
                }
                if user_role_ids & set(bypass_role_ids):
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
        if "users" in approver_config and actor.id in approver_config["users"]:
            return True

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
