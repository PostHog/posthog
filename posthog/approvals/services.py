import logging
from dataclasses import dataclass
from typing import Any, Optional

from django.db import transaction
from django.utils import timezone

from posthog.approvals.actions.registry import get_action
from posthog.approvals.exceptions import (
    AlreadyVotedError,
    ApplyFailed,
    InvalidStateError,
    PreconditionFailed,
    ReasonRequiredError,
)
from posthog.approvals.models import Approval, ApprovalDecision, ChangeRequest, ChangeRequestState
from posthog.approvals.notifications import send_approval_applied_notification, send_approval_decision_notification
from posthog.event_usage import report_user_action
from posthog.models import User

logger = logging.getLogger(__name__)


class RequestContext:
    def __init__(self, method: str, user, data: dict):
        self.method = method
        self.user = user
        self.data = data
        self.session: dict[str, Any] = {}


def apply_change_request(change_request: ChangeRequest) -> Any:
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

    def __init__(self, change_request: ChangeRequest, user: User):
        self.change_request = change_request
        self.user = user

    def approve(self, reason: str = "") -> ApproveResult:
        """
        Approve a change request.
        If quorum is reached, automatically applies the change.
        """
        if self.change_request.state != ChangeRequestState.PENDING:
            raise InvalidStateError("Only pending change requests can be approved")

        with transaction.atomic():
            change_request = ChangeRequest.objects.select_for_update().get(pk=self.change_request.pk)

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

                logger.info(
                    "Quorum reached, auto-applying change request",
                    extra={
                        "change_request_id": str(change_request.id),
                        "action_key": change_request.action_key,
                    },
                )

                try:
                    result = apply_change_request(change_request)
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
        if self.change_request.state != ChangeRequestState.PENDING:
            raise InvalidStateError("Only pending change requests can be canceled")

        with transaction.atomic():
            change_request = ChangeRequest.objects.select_for_update().get(pk=self.change_request.pk)

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
