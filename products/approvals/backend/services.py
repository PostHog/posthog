import logging
from dataclasses import dataclass
from typing import Any, Optional, cast

from django.db import transaction
from django.utils import timezone

from prometheus_client import Counter

from posthog.api.utils import ServiceRequest
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.scopes import API_SCOPE_OBJECTS, APIScopeObject

from products.access_control.backend.facade.user_access_control import UserAccessControl, model_to_resource
from products.approvals.backend.actions.registry import get_action
from products.approvals.backend.exceptions import (
    AlreadyVotedError,
    ApplyFailed,
    InvalidStateError,
    PreconditionFailed,
    ReasonRequiredError,
    StaleChangeRequestError,
)
from products.approvals.backend.models import (
    Approval,
    ApprovalDecision,
    ChangeRequest,
    ChangeRequestState,
    ValidationStatus,
)
from products.approvals.backend.notifications import (
    send_approval_applied_notification,
    send_approval_decision_notification,
)
from products.approvals.backend.ownership import owner_kind_changed

logger = logging.getLogger(__name__)

# Approved changes refused at apply because a different product owns the resource now. This is
# the blast radius of binding an approval to the ownership it was reviewed under: every increment
# is a change an approver said yes to that did not land. recorded/current carry owner kinds, which
# are a closed set, so the label stays bounded.
OWNERSHIP_MISMATCH_COUNTER = Counter(
    "posthog_approvals_apply_ownership_mismatch_total",
    "Approved change requests refused at apply because the resource owner changed",
    labelnames=["action", "recorded", "current"],
)


class RequestContext(ServiceRequest):
    """The request shim an apply replays a serializer write under.

    An apply is not an authenticated read, so `successful_authenticator` stays None and a
    serializer keeps an encrypted flag payload redacted.
    """

    def __init__(self, method: str, user, data: dict, skip_opportunistic_filter_cleanup: bool = False):
        super().__init__(user, method=method)
        self.data = data
        # Carried from the original request via the intent. A write that sent no filters must not
        # have them rewritten on replay either, and the exemption cannot be inferred here: an
        # approved ordinary update should still get the cleanup.
        self.skip_opportunistic_filter_cleanup = skip_opportunistic_filter_cleanup


def requester_still_has_access(change_request: ChangeRequest, context: dict[str, Any]) -> bool:
    """Whether the person who raised this change request could still make it themselves.

    Shared by the apply path, which refuses, and the periodic validation task, which marks the
    request invalid and clears that mark once access returns.
    """
    requester = change_request.created_by
    if requester is None:
        # `created_by` is SET_NULL, so deleting the requester's account empties it. Nobody is
        # left whose access can be checked, and unknown means deny, as it does everywhere else
        # in this gate.
        return False

    access = UserAccessControl(user=requester, team=change_request.team)
    instance = context.get("instance")

    if instance is None:
        # A create has no row yet, so only the resource axis exists. Returning True here instead
        # would leave the create path unchecked, which is the path a revoked user most wants.
        resource = change_request.resource_type if change_request.resource_type in API_SCOPE_OBJECTS else None
        if resource is None:
            return True
        return access.check_access_level_for_resource(cast(APIScopeObject, resource), "editor")

    # Both axes have to hold, the way they do for a direct write. A resource-wide control set to
    # "none" denies the write even while the object-level level still reads as manager, so
    # checking only the object would let the apply through where the API returns 403.
    object_resource = model_to_resource(instance)
    return access.check_access_level_for_object(instance, "editor") and (
        object_resource is None or access.check_access_level_for_resource(object_resource, "editor")
    )


def _assert_requester_still_has_access(change_request: ChangeRequest, context: dict[str, Any]) -> None:
    """Refuse to apply a change the requester may no longer make themselves.

    Access is checked when a change request is created, because the viewset's access control
    runs before the gate on the serializer. It is not checked again here: an apply replays the
    write through a request shim with no authenticated user, so no permission layer runs. Without
    this, someone who loses edit access between asking and approval still gets their change
    landed, and approval becomes a way to outlive your own permissions.

    The request is marked invalid rather than failed. The periodic validation task clears that
    mark once access returns, so the request becomes applicable again on its own.
    """
    if requester_still_has_access(change_request, context):
        return

    change_request.validation_status = ValidationStatus.INVALID
    change_request.validation_errors = {
        "access": "The requester no longer has edit access to this resource, or their account is gone."
    }
    change_request.validated_at = timezone.now()
    change_request.save(update_fields=["validation_status", "validation_errors", "validated_at"])
    raise PreconditionFailed(
        "The person who requested this change no longer has edit access to the resource, "
        "so it cannot be applied. Ask them to request it again if their access is restored."
    )


def mark_stale_if_resource_changed(change_request: ChangeRequest) -> bool:
    """Mark the request stale and return True if its resource changed after the request was made.

    The apply step refuses a stale request anyway. This check runs before a vote, so an approver
    does not learn about the conflict only after the vote is cast.
    """
    action_class = get_action(change_request.action_key)
    if not action_class:
        return False

    base_context = {
        "team": change_request.team,
        "team_id": change_request.team_id,
        "organization": change_request.organization,
    }
    context = action_class.prepare_context(change_request, base_context)
    if not action_class.check_staleness(change_request.intent, context):
        return False

    change_request.validation_status = ValidationStatus.STALE
    change_request.validation_errors = {"staleness": "Resource has been modified since this change request was created"}
    change_request.validated_at = timezone.now()
    change_request.save(update_fields=["validation_status", "validation_errors", "validated_at"])
    return True


def apply_change_request(change_request: ChangeRequest, request=None) -> Any:
    """
    Apply an approved change request.

    Steps:
    1. Lookup action
    2. Re-validate intent
    3. Check preconditions
    4. Call action.apply()
    5. Mark as APPLIED
    6. Emit events
    """

    action_class = get_action(change_request.action_key)
    if not action_class:
        raise ApplyFailed(f"Action {change_request.action_key} not found in registry")

    # Create minimal request context for serializers that need it
    # All data comes from ChangeRequest - nothing stored separately!
    request_context = RequestContext(
        method=change_request.intent.get("http_method", "PATCH"),  # Stored in intent JSON
        user=change_request.created_by,  # Already in ChangeRequest
        data=change_request.intent.get("gated_changes", change_request.intent),  # Already in ChangeRequest
        skip_opportunistic_filter_cleanup=bool(change_request.intent.get("skip_opportunistic_filter_cleanup")),
    )

    # Build base context with common metadata
    base_context = {
        "team": change_request.team,
        "team_id": change_request.team_id,
        "project_id": change_request.team.project_id,
        "organization": change_request.organization,
        "request": request_context,
    }

    # Let the action prepare its own context (e.g., fetch instance)
    validation_context = action_class.prepare_context(change_request, base_context)

    _assert_requester_still_has_access(change_request, validation_context)

    current_owner_kind = action_class.derive_owner_kind(
        change_request.team, change_request.resource_id, change_request.intent
    )
    if owner_kind_changed(change_request.owner_kind, current_owner_kind):
        # The approvers reviewed this change against one owner, and a different product owns the
        # resource now. Which policy applies is keyed on that owner, so applying would land a
        # change nobody with the current owner's policy ever saw.
        OWNERSHIP_MISMATCH_COUNTER.labels(
            action=change_request.action_key,
            recorded=change_request.owner_kind,
            current=current_owner_kind,
        ).inc()
        change_request.state = ChangeRequestState.FAILED
        change_request.apply_error = (
            f"Ownership changed since this request was created: {change_request.owner_kind} -> {current_owner_kind}"
        )
        change_request.save()
        raise PreconditionFailed(
            "This resource now belongs to a different product than when the change was requested. "
            "Request the change again so the right approvers review it."
        )

    is_valid, errors = action_class.validate_intent(
        change_request.intent,
        context=validation_context,
    )

    if not is_valid:
        change_request.state = ChangeRequestState.FAILED
        change_request.apply_error = f"Validation failed: {errors}"
        change_request.save()
        raise ApplyFailed(f"Intent no longer valid: {errors}")

    try:
        with transaction.atomic():
            # Let the action prepare its own apply context
            apply_context = action_class.prepare_context(change_request, base_context)

            result = action_class.apply(
                validated_intent=change_request.intent,
                user=change_request.created_by,
                context=apply_context,
            )

            change_request.state = ChangeRequestState.APPLIED
            change_request.applied_at = timezone.now()
            change_request.applied_by = change_request.created_by
            change_request.result_data = {
                "resource_id": getattr(result, "id", None),
                "resource_version": getattr(result, "version", None),
            }
            change_request.save()

        logger.info(
            "Applied ChangeRequest",
            extra={
                "change_request_id": str(change_request.id),
                "action": change_request.action_key,
            },
        )

        if change_request.created_by:
            report_user_action(
                change_request.created_by,
                "approval_applied",
                {
                    "action_key": change_request.action_key,
                    "change_request_id": str(change_request.id),
                },
                team=change_request.team,
                request=request,
            )

        send_approval_applied_notification(change_request)

        return result

    except PreconditionFailed as e:
        change_request.state = ChangeRequestState.FAILED
        change_request.apply_error = f"Precondition failed: {str(e)}"
        change_request.save()

        logger.warning(
            "Failed to apply ChangeRequest: precondition failed",
            extra={
                "change_request_id": str(change_request.id),
                "error": str(e),
            },
        )
        raise

    except Exception as e:
        change_request.state = ChangeRequestState.FAILED
        change_request.apply_error = str(e)
        change_request.save()

        logger.error(
            "Failed to apply ChangeRequest",
            extra={
                "change_request_id": str(change_request.id),
                "error": str(e),
            },
            exc_info=True,
        )
        raise ApplyFailed(f"Apply failed: {str(e)}")


@dataclass
class ServiceResult:
    status: str
    message: str
    change_request: ChangeRequest


@dataclass
class ApproveResult(ServiceResult):
    auto_applied: bool = False
    result_data: Optional[dict] = None


@dataclass
class RejectResult(ServiceResult):
    pass


@dataclass
class CancelResult(ServiceResult):
    pass


class ChangeRequestService:
    """Service for managing change request lifecycle operations."""

    def __init__(self, change_request: ChangeRequest, user: User, request=None):
        self.change_request = change_request
        self.user = user
        self._request = request

    def approve(self, reason: str = "") -> ApproveResult:
        """
        Approve a change request.
        If quorum is reached, automatically applies the change.
        """
        if self.change_request.state != ChangeRequestState.PENDING:
            raise InvalidStateError("Only pending change requests can be approved")

        if mark_stale_if_resource_changed(self.change_request):
            raise StaleChangeRequestError(
                "This resource changed after the request was made, so the change can no longer be applied. "
                "Request the change again."
            )

        with transaction.atomic():
            change_request = ChangeRequest.objects.select_for_update().get(pk=self.change_request.pk)

            if change_request.state != ChangeRequestState.PENDING:
                raise InvalidStateError("Only pending change requests can be approved")

            approval, created = Approval.objects.get_or_create(
                change_request=change_request,
                created_by=self.user,
                defaults={"decision": ApprovalDecision.APPROVED, "reason": reason},
            )

            if not created:
                raise AlreadyVotedError("You have already voted on this change request")

            report_user_action(
                self.user,
                "approval_vote_cast",
                {
                    "change_request_id": str(change_request.id),
                    "action_key": change_request.action_key,
                    "decision": ApprovalDecision.APPROVED,
                },
                team=change_request.team,
                request=self._request,
            )

            approval_count = change_request.approvals.filter(decision=ApprovalDecision.APPROVED).count()
            required_quorum = change_request.policy_snapshot.get("quorum", 1)

            logger.info(
                "Approval cast",
                extra={
                    "change_request_id": str(change_request.id),
                    "user_id": self.user.id,
                    "approval_count": approval_count,
                    "required_quorum": required_quorum,
                },
            )

            self._send_decision_notification(change_request, approval)

            if approval_count >= required_quorum:
                change_request.state = ChangeRequestState.APPROVED
                change_request.save()

                # A change request bound to a scheduled change must not be applied on approval:
                # the scheduled applier (process_scheduled_changes) applies it only once
                # scheduled_at is reached. Auto-applying here would let an approver fire a
                # future-dated flag change immediately, defeating the schedule.
                if change_request.scheduled_changes.exists():
                    logger.info(
                        "Quorum reached for scheduled change; deferring application to fire time",
                        extra={
                            "change_request_id": str(change_request.id),
                            "action_key": change_request.action_key,
                        },
                    )
                    return ApproveResult(
                        status="approved",
                        message="Quorum reached. Change approved and will be applied at its scheduled time.",
                        change_request=change_request,
                        auto_applied=False,
                    )

                logger.info(
                    "Quorum reached, auto-applying change request",
                    extra={
                        "change_request_id": str(change_request.id),
                        "action_key": change_request.action_key,
                    },
                )

                try:
                    result = apply_change_request(change_request, request=self._request)
                    return ApproveResult(
                        status="applied",
                        message="Quorum reached. Change applied successfully.",
                        change_request=change_request,
                        auto_applied=True,
                        result_data={
                            "resource_id": getattr(result, "id", None),
                            "resource_version": getattr(result, "version", None),
                        },
                    )
                except Exception as e:
                    logger.exception(
                        "Failed to auto-apply change request",
                        extra={
                            "change_request_id": str(change_request.id),
                            "error": str(e),
                        },
                    )
                    return ApproveResult(
                        status="failed",
                        message=f"Quorum reached but application failed: {str(e)}",
                        change_request=change_request,
                        auto_applied=False,
                    )

            return ApproveResult(
                status="approved",
                message=f"Approval recorded. {approval_count}/{required_quorum} approvals received.",
                change_request=change_request,
                auto_applied=False,
            )

    def reject(self, reason: str) -> RejectResult:
        if self.change_request.state != ChangeRequestState.PENDING:
            raise InvalidStateError("Only pending change requests can be rejected")

        if not reason:
            raise ReasonRequiredError("Reason is required for rejection")

        with transaction.atomic():
            change_request = ChangeRequest.objects.select_for_update().get(pk=self.change_request.pk)

            if change_request.state != ChangeRequestState.PENDING:
                raise InvalidStateError("Only pending change requests can be rejected")

            approval, created = Approval.objects.get_or_create(
                change_request=change_request,
                created_by=self.user,
                defaults={"decision": ApprovalDecision.REJECTED, "reason": reason},
            )

            if not created:
                raise AlreadyVotedError("You have already voted on this change request")

            self._send_decision_notification(change_request, approval)

            change_request.state = ChangeRequestState.REJECTED
            change_request.save()

            report_user_action(
                self.user,
                "approval_vote_cast",
                {
                    "change_request_id": str(change_request.id),
                    "action_key": change_request.action_key,
                    "decision": ApprovalDecision.REJECTED,
                },
                team=change_request.team,
                request=self._request,
            )

            logger.info(
                "Change request rejected",
                extra={
                    "change_request_id": str(change_request.id),
                    "user_id": self.user.id,
                    "reason": reason,
                },
            )

        return RejectResult(
            status="rejected",
            message="Change request rejected.",
            change_request=change_request,
        )

    def cancel(self, reason: str = "Canceled by requester") -> CancelResult:
        with transaction.atomic():
            change_request = ChangeRequest.objects.select_for_update().get(pk=self.change_request.pk)

            if not change_request.can_be_canceled_by(self.user.id):
                raise InvalidStateError("Cannot cancel this change request")

            # Create a rejection record with the cancellation reason
            Approval.objects.create(
                change_request=change_request,
                created_by=self.user,
                decision=ApprovalDecision.REJECTED,
                reason=reason,
            )

            change_request.state = ChangeRequestState.REJECTED
            change_request.save()

            report_user_action(
                self.user,
                "change_request_canceled",
                {
                    "change_request_id": str(change_request.id),
                    "action_key": change_request.action_key,
                    "reason": reason,
                },
                team=change_request.team,
                request=self._request,
            )

            logger.info(
                "Change request canceled",
                extra={
                    "change_request_id": str(change_request.id),
                    "user_id": self.user.id,
                    "reason": reason,
                },
            )

        return CancelResult(
            status="canceled",
            message="Change request canceled.",
            change_request=change_request,
        )

    def _send_decision_notification(self, change_request: ChangeRequest, approval: Approval) -> None:
        """Send notification about the approval decision."""
        try:
            send_approval_decision_notification(change_request, approval)
        except Exception as e:
            logger.warning(
                "Failed to send approval notification",
                extra={
                    "change_request_id": str(change_request.id),
                    "error": str(e),
                },
            )
