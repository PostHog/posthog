from rest_framework import status
from rest_framework.response import Response

from posthog.approvals.exceptions import ApprovalRequired
from posthog.approvals.serializers import ChangeRequestSerializer


class ApprovalHandlingMixin:
    """
    Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.

    This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
    on serializer methods and converts them into proper HTTP 409 Conflict responses with
    change request details.
    """

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, ApprovalRequired):
            return Response(
                {
                    "code": exc.error_code,
                    "status": "approval_required",
                    "detail": exc.message,
                    "message": exc.message,
                    "resource_type": exc.change_request.resource_type,
                    "resource_id": exc.change_request.resource_id,
                    "change_request_id": str(exc.change_request.id),
                    "change_request": ChangeRequestSerializer(exc.change_request).data,
                    "required_approvers": exc.required_approvers,
                },
                status=status.HTTP_409_CONFLICT,
            )

        return super().handle_exception(exc)  # type: ignore[misc]
