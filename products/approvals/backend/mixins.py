from rest_framework import status
from rest_framework.response import Response

from products.approvals.backend.exceptions import ApprovalRequired, PolicyConflict
from products.approvals.backend.serializers import ChangeRequestSerializer


class ApprovalHandlingMixin:
    """
    Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.

    Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
    decorator on serializer methods and converts them into the same responses the viewset path
    produces (see decorators._result_to_response), so both paths share one contract.
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

        if isinstance(exc, PolicyConflict):
            return Response(
                {
                    "code": "policy_conflict",
                    "error": exc.message,
                    "conflicting_policies": exc.conflicting_policies,
                    "guidance": exc.guidance,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().handle_exception(exc)  # type: ignore[misc]
