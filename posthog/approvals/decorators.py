import logging
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Literal, Optional, Union

from django.conf import settings
from django.utils import timezone

import posthoganalytics
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response

from posthog.approvals.actions.registry import get_action
from posthog.approvals.exceptions import ApprovalRequired
from posthog.approvals.models import ChangeRequest, ChangeRequestState
from posthog.approvals.notifications import send_approval_requested_notification
from posthog.approvals.policies import PolicyDecision, PolicyEngine
from posthog.approvals.serializers import ChangeRequestSerializer
from posthog.event_usage import report_user_action

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    """Result of evaluating the approval gate - pure data, no HTTP concerns."""

    action: Literal[
        "passthrough", "deny", "require_approval", "duplicate", "validation_error", "error", "policy_conflict"
    ]
    change_request: Optional[ChangeRequest] = None
    decision: Optional[PolicyDecision] = None
    error_message: Optional[str] = None
    validation_errors: Optional[dict] = None
    resource_id: Optional[str] = None
    resource_type: Optional[str] = None
    approvers: dict = field(default_factory=dict)
    conflicting_policies: list = field(default_factory=list)


def _extract_context(view_or_serializer, request=None) -> tuple[Optional[Any], Optional[Any], Optional[Any]]:
    """Extract request, team, organization from either serializer or viewset."""
    if hasattr(view_or_serializer, "context") and isinstance(view_or_serializer.context, dict):
        req = view_or_serializer.context.get("request")
        team = view_or_serializer.context.get("get_team", lambda: None)()
        org = view_or_serializer.context.get("get_organization", lambda: None)()
        return req, team, org
    else:
        team = getattr(view_or_serializer, "team", None)
        org = getattr(view_or_serializer, "organization", None)
        return request, team, org


def _is_approvals_enabled(organization) -> bool:
    """Check if the approvals feature flag is enabled for this organization."""
    return posthoganalytics.feature_enabled(
        key="approvals",
        distinct_id=str(organization.id),
        groups={"organization": str(organization.id)},
    )


def _check_policy_for_action(action_class, team, organization) -> Optional[Any]:
    """Check if there's an enabled policy for this action."""
    policy_engine = PolicyEngine()
    policy = policy_engine.get_policy(
        action_key=action_class.key,
        team=team,
        organization=organization,
    )
    if policy and policy.enabled:
        return policy
    return None


def _check_for_duplicate(action_class, team, resource_id: Optional[str]) -> Optional[ChangeRequest]:
    """Check if there's already a pending/approved change request."""
    return ChangeRequest.objects.filter(
        action_key=action_class.key,
        team=team,
        resource_type=action_class.resource_type,
        resource_id=resource_id,
        state__in=[ChangeRequestState.PENDING, ChangeRequestState.APPROVED],
    ).first()


def _check_for_policy_conflicts(action_class, team, organization, intent_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Check if multiple policies match the same change.
    Returns list of conflicting policy info dicts if more than one policy matches.
    """
    policy_engine = PolicyEngine()
    matching_policies = policy_engine.get_all_matching_policies(
        action_key=action_class.key,
        team=team,
        organization=organization,
        intent=intent_data,
    )

    if len(matching_policies) > 1:
        return [{"id": str(p.id), "name": str(p)} for p in matching_policies]

    return []


def _create_change_request(
    action_class,
    team,
    organization,
    resource_id: Optional[str],
    intent_data: dict[str, Any],
    display_data: dict[str, Any],
    policy_snapshot: dict[str, Any],
    user,
    expires_at,
) -> ChangeRequest:
    """Create and log a ChangeRequest record."""
    change_request = ChangeRequest.objects.create(
        action_key=action_class.key,
        action_version=action_class.version,
        team=team,
        organization=organization,
        resource_type=action_class.resource_type,
        resource_id=resource_id,
        intent=intent_data,
        intent_display=display_data,
        policy_snapshot=policy_snapshot,
        created_by=user,
        state=ChangeRequestState.PENDING,
        expires_at=expires_at,
    )

    logger.info(
        "Created ChangeRequest",
        extra={
            "change_request_id": str(change_request.id),
            "action": action_class.key,
            "user": user.id,
        },
    )

    report_user_action(
        user,
        "approval_requested",
        {
            "action_key": action_class.key,
            "change_request_id": str(change_request.id),
            "resource_type": action_class.resource_type,
        },
    )

    send_approval_requested_notification(change_request)

    return change_request


def _build_context(view_or_serializer, team, organization, request) -> dict[str, Any]:
    """Build validation context, preserving serializer context if available."""
    if hasattr(view_or_serializer, "context") and isinstance(view_or_serializer.context, dict):
        context = view_or_serializer.context.copy()
        context.update({"team": team, "organization": organization})
        if hasattr(view_or_serializer, "instance") and view_or_serializer.instance is not None:
            context["instance"] = view_or_serializer.instance
        return context
    else:
        return {
            "team": team,
            "team_id": team.id,
            "organization": organization,
            "request": request,
            "view": view_or_serializer,
        }


def _extract_resource_id(request, args: tuple, kwargs: dict) -> Optional[str]:
    """Extract resource ID from request context."""
    if request.method == "POST":
        return None
    if args and hasattr(args[0], "id"):
        return str(args[0].id)
    if kwargs.get("pk"):
        return str(kwargs["pk"])
    return None


def _evaluate_gate(
    action_class,
    request,
    team,
    organization,
    policy,
    view_or_serializer,
    args: tuple,
    kwargs: dict,
) -> GateResult:
    """
    Core approval gate logic. Returns a result object describing what should happen.
    Called after detect() has already matched - skips detection step.
    """
    logger.info(
        "Evaluating approval gate",
        extra={
            "action": action_class.key,
            "user": request.user.id,
            "method": request.method,
            "path": request.path,
        },
    )

    # Step 1: Extract intent
    try:
        intent_data = action_class.extract_intent(request, view_or_serializer, *args, **kwargs)
        if not isinstance(intent_data, dict):
            intent_data = dict(intent_data)
        else:
            intent_data = intent_data.copy()
        intent_data["http_method"] = request.method
    except Exception as e:
        logger.error(
            "Error extracting intent",
            extra={"action": action_class.key, "error": str(e)},
            exc_info=True,
        )
        return GateResult(action="error", error_message="Failed to process approval request")

    # Step 2: Validate intent
    context = _build_context(view_or_serializer, team, organization, request)
    is_valid, errors = action_class.validate_intent(intent_data, context)
    if not is_valid:
        logger.warning("Intent validation failed", extra={"action": action_class.key, "errors": errors})
        return GateResult(action="validation_error", validation_errors=errors)

    # Step 3: Check for policy conflicts BEFORE creating ChangeRequest
    conflicting_policies = _check_for_policy_conflicts(action_class, team, organization, intent_data)
    if conflicting_policies:
        logger.warning(
            "Multiple policies match this change",
            extra={
                "action": action_class.key,
                "conflicting_policies": conflicting_policies,
            },
        )
        return GateResult(
            action="policy_conflict",
            conflicting_policies=conflicting_policies,
            error_message="This change matches multiple approval policies",
        )

    # Step 4: Evaluate policy
    policy_engine = PolicyEngine()
    decision = policy_engine.evaluate(
        policy=policy,
        actor=request.user,
        intent=intent_data,
        context=context,
    )

    if decision.result == "ALLOW":
        logger.info(
            "Policy allows immediate execution",
            extra={"action": action_class.key, "reason": decision.reason},
        )
        return GateResult(action="passthrough")

    if decision.result == "DENY":
        logger.warning("Policy denied request", extra={"action": action_class.key, "reason": decision.reason})
        return GateResult(action="deny", error_message=decision.reason)

    # Step 5: REQUIRE_APPROVAL - check for duplicates and create change request
    resource_id = _extract_resource_id(request, args, kwargs)

    existing = _check_for_duplicate(action_class, team, resource_id)
    if existing:
        logger.info(
            "Rejecting duplicate change request",
            extra={
                "action": action_class.key,
                "resource_id": resource_id,
                "existing_request_id": str(existing.id),
                "existing_state": existing.state,
            },
        )
        return GateResult(
            action="duplicate",
            change_request=existing,
            resource_id=resource_id,
            resource_type=action_class.resource_type,
        )

    # Create the change request
    try:
        display_data = action_class.get_display_data(intent_data)
        expires_at = timezone.now() + policy.expires_after

        change_request = _create_change_request(
            action_class=action_class,
            team=team,
            organization=organization,
            resource_id=resource_id,
            intent_data=intent_data,
            display_data=display_data,
            policy_snapshot=decision.policy_snapshot,
            user=request.user,
            expires_at=expires_at,
        )

        return GateResult(
            action="require_approval",
            change_request=change_request,
            decision=decision,
            resource_id=resource_id,
            resource_type=action_class.resource_type,
            approvers=decision.approvers,
        )
    except Exception as e:
        logger.error(
            "Failed to create ChangeRequest",
            extra={"action": action_class.key, "error": str(e), "error_type": type(e).__name__},
            exc_info=True,
        )
        error_msg = (
            f"Failed to create approval request: {type(e).__name__}: {str(e)}"
            if settings.DEBUG
            else "Failed to create approval request"
        )
        return GateResult(action="error", error_message=error_msg)


def _result_to_exception(result: GateResult) -> None:
    """Convert GateResult to exceptions for serializer context. Returns None for passthrough."""
    if result.action == "passthrough":
        return

    if result.action == "validation_error":
        raise ValidationError(result.validation_errors)

    if result.action == "deny":
        raise PermissionDenied(f"This action is not allowed by approval policy: {result.error_message}")

    if result.action == "error":
        raise APIException(result.error_message)

    if result.action == "policy_conflict":
        raise ValidationError(
            {
                "code": "policy_conflict",
                "error": result.error_message,
                "conflicting_policies": result.conflicting_policies,
                "guidance": "Split your changes into separate API calls to address each policy independently",
            }
        )

    if result.action == "duplicate":
        raise ApprovalRequired(
            change_request=result.change_request,
            message="A pending approval request already exists for this action",
            required_approvers={},
            error_code="change_request_pending",
        )

    if result.action == "require_approval":
        raise ApprovalRequired(
            change_request=result.change_request,
            message=result.decision.message if result.decision else "Approval required",
            required_approvers=result.approvers,
        )


def _result_to_response(result: GateResult) -> Optional[Response]:
    """Convert GateResult to Response for viewset context. Returns None for passthrough."""
    if result.action == "passthrough":
        return None

    if result.action == "validation_error":
        return Response({"validation_errors": result.validation_errors}, status=status.HTTP_400_BAD_REQUEST)

    if result.action == "deny":
        return Response(
            {"error": "This action is not allowed by approval policy", "reason": result.error_message},
            status=status.HTTP_403_FORBIDDEN,
        )

    if result.action == "error":
        return Response({"error": result.error_message}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    if result.action == "policy_conflict":
        return Response(
            {
                "code": "policy_conflict",
                "error": result.error_message,
                "conflicting_policies": result.conflicting_policies,
                "guidance": "Split your changes into separate API calls to address each policy independently",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if result.action == "duplicate" and result.change_request:
        return Response(
            {
                "code": "change_request_pending",
                "error": "A pending approval request already exists for this action",
                "resource_type": result.resource_type,
                "resource_id": result.resource_id,
                "change_request_id": str(result.change_request.id),
                "existing_change_request": ChangeRequestSerializer(result.change_request).data,
            },
            status=status.HTTP_409_CONFLICT,
        )

    if result.action == "require_approval" and result.change_request:
        return Response(
            {
                "code": "approval_required",
                "status": "approval_required",
                "message": result.decision.message if result.decision else "Approval required",
                "resource_type": result.resource_type,
                "resource_id": result.resource_id,
                "change_request_id": str(result.change_request.id),
                "change_request": ChangeRequestSerializer(result.change_request).data,
                "required_approvers": result.approvers,
            },
            status=status.HTTP_409_CONFLICT,
        )

    return None


def _resolve_actions(action_refs: Union[type, str, list]) -> list:
    """Resolve action reference(s) to a list of action classes."""
    if isinstance(action_refs, list):
        refs = action_refs
    else:
        refs = [action_refs]

    actions = []
    for ref in refs:
        if isinstance(ref, str):
            action_class = get_action(ref)
            if action_class:
                actions.append(action_class)
            else:
                raise ValueError(f"Failed to resolve action reference: {ref}")
        else:
            actions.append(ref)

    return actions


def approval_gate(action_refs: Union[type, str, list]):
    """
    Decorator that gates serializer or viewset methods with approval workflow.

    Args:
        action_refs: Single action reference or list of action references.
                    Each action's detect() is called until one matches.
    """

    def decorator(method):
        @wraps(method)
        def wrapper(self, *args, **kwargs):
            actions = _resolve_actions(action_refs)
            if not actions:
                return method(self, *args, **kwargs)

            is_serializer = hasattr(self, "context") and isinstance(self.context, dict) and "request" in self.context

            if is_serializer:
                request, team, organization = _extract_context(self)
            else:
                request = args[0] if args else kwargs.get("request")
                _, team, organization = _extract_context(self, request)

            if not team or not organization:
                logger.warning(
                    f"No team/org context in {'serializer' if is_serializer else 'viewset'}, skipping approval gate"
                )
                return method(self, *args, **kwargs)

            if not _is_approvals_enabled(organization):
                return method(self, *args, **kwargs)

            # Find first action that matches and has a policy
            matched_action = None
            matched_policy = None

            for action_class in actions:
                try:
                    if action_class.detect(request, self, *args, **kwargs):
                        policy = _check_policy_for_action(action_class, team, organization)
                        if policy:
                            matched_action = action_class
                            matched_policy = policy
                            break
                except Exception as e:
                    logger.error(
                        "Error in action detect()",
                        extra={"action": action_class.key, "error": str(e)},
                        exc_info=True,
                    )

            if not matched_action or not matched_policy:
                return method(self, *args, **kwargs)

            # Evaluate the gate with matched action
            result = _evaluate_gate(
                action_class=matched_action,
                request=request,
                team=team,
                organization=organization,
                policy=matched_policy,
                view_or_serializer=self,
                args=args,
                kwargs=kwargs,
            )

            # Convert result to appropriate output format
            if is_serializer:
                _result_to_exception(result)
                return method(self, *args, **kwargs)
            else:
                response = _result_to_response(result)
                if response is not None:
                    return response
                return method(self, *args, **kwargs)

        return wrapper

    return decorator
