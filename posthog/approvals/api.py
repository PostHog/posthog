import logging

from django.db.models import QuerySet

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.approvals.exceptions import AlreadyVotedError, InvalidStateError, ReasonRequiredError
from posthog.approvals.models import ApprovalPolicy, ChangeRequest
from posthog.approvals.permissions import CanApprove, CanCancel
from posthog.approvals.serializers import ApprovalPolicySerializer, ChangeRequestSerializer
from posthog.approvals.services import ChangeRequestService
from posthog.permissions import OrganizationAdminWritePermissions, OrganizationMemberPermissions

logger = logging.getLogger(__name__)


class ChangeRequestViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"
    queryset = ChangeRequest.objects.all().order_by("-created_at")
    permission_classes = [OrganizationMemberPermissions]
    serializer_class = ChangeRequestSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        filters = self.request.query_params

        if "state" in filters:
            states = filters["state"].split(",")
            queryset = queryset.filter(state__in=states)

        action_filter = filters.get("action_type") or filters.get("action_key")
        if action_filter:
            queryset = queryset.filter(action_key=action_filter)

        if "requester" in filters:
            queryset = queryset.filter(created_by_id=filters["requester"])

        if "resource_type" in filters:
            queryset = queryset.filter(resource_type=filters["resource_type"])

        if "resource_id" in filters:
            queryset = queryset.filter(resource_id=filters["resource_id"])

        return queryset.select_related("created_by", "applied_by").prefetch_related("approvals")

    @action(methods=["POST"], detail=True, permission_classes=[CanApprove])
    def approve(self, request: Request, pk=None, **kwargs) -> Response:
        """
        Approve a change request.
        If quorum is reached, automatically applies the change immediately.
        """
        change_request: ChangeRequest = self.get_object()
        service = ChangeRequestService(change_request, request.user)

        try:
            result = service.approve(reason=request.data.get("reason", ""))
        except InvalidStateError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except AlreadyVotedError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        response_data = {
            "status": result.status,
            "message": result.message,
            "change_request": ChangeRequestSerializer(result.change_request).data,
        }
        if result.result_data:
            response_data["result"] = result.result_data

        return Response(response_data, status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True, permission_classes=[CanApprove])
    def reject(self, request: Request, pk=None, **kwargs) -> Response:
        """Reject a change request."""
        change_request: ChangeRequest = self.get_object()
        service = ChangeRequestService(change_request, request.user)

        try:
            result = service.reject(reason=request.data.get("reason", ""))
        except InvalidStateError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ReasonRequiredError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except AlreadyVotedError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "status": result.status,
                "message": result.message,
                "change_request": ChangeRequestSerializer(result.change_request).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(methods=["POST"], detail=True, permission_classes=[CanCancel])
    def cancel(self, request: Request, pk=None, **kwargs) -> Response:
        """
        Cancel a change request.
        Only the requester can cancel their own pending change request.
        """
        change_request: ChangeRequest = self.get_object()
        service = ChangeRequestService(change_request, request.user)

        try:
            result = service.cancel(reason=request.data.get("reason", "Canceled by requester"))
        except InvalidStateError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "status": result.status,
                "message": result.message,
                "change_request": ChangeRequestSerializer(result.change_request).data,
            },
            status=status.HTTP_200_OK,
        )


class ApprovalPolicyViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ApprovalPolicy.objects.all().order_by("-created_at")
    serializer_class = ApprovalPolicySerializer
    permission_classes = [OrganizationMemberPermissions, OrganizationAdminWritePermissions]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        filters = self.request.query_params

        if "action_key" in filters:
            queryset = queryset.filter(action_key=filters["action_key"])

        if "enabled" in filters:
            enabled = filters["enabled"].lower() == "true"
            queryset = queryset.filter(enabled=enabled)

        return queryset.select_related("created_by")

    def perform_create(self, serializer: ApprovalPolicySerializer) -> None:
        serializer.save(
            created_by=self.request.user,
            organization=self.organization,
            team=self.team if hasattr(self, "team") else None,
        )
