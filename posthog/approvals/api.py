import logging
from typing import cast

from django.db import IntegrityError
from django.db.models import QuerySet

from rest_framework import exceptions, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.approvals.exceptions import AlreadyVotedError, InvalidStateError, ReasonRequiredError
from posthog.approvals.models import ApprovalPolicy, ChangeRequest
from posthog.approvals.permissions import CanApprove, CanCancel
from posthog.approvals.serializers import ApprovalPolicySerializer, ChangeRequestSerializer
from posthog.approvals.services import ChangeRequestService
from posthog.models import User
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
        service = ChangeRequestService(change_request, cast(User, request.user))

        try:
            result = service.approve(reason=request.data.get("reason", ""))
        except InvalidStateError:
            return Response(
                {"error": "This change request can no longer be approved."}, status=status.HTTP_400_BAD_REQUEST
            )
        except AlreadyVotedError:
            return Response(
                {"error": "You have already voted on this change request."}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error("Unexpected error in approve: %s", str(e), exc_info=True)
            return Response(
                {"error": "An error occurred while processing approval."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        response_data = {
            "status": result.status,
            "message": result.message,
            "change_request": ChangeRequestSerializer(result.change_request, context={"request": request}).data,
        }
        if result.result_data:
            response_data["result"] = result.result_data

        return Response(response_data, status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True, permission_classes=[CanApprove])
    def reject(self, request: Request, pk=None, **kwargs) -> Response:
        """Reject a change request."""
        change_request: ChangeRequest = self.get_object()
        service = ChangeRequestService(change_request, cast(User, request.user))

        try:
            result = service.reject(reason=request.data.get("reason", ""))
        except InvalidStateError:
            return Response(
                {"error": "This change request can no longer be rejected."}, status=status.HTTP_400_BAD_REQUEST
            )
        except ReasonRequiredError:
            return Response({"error": "A reason is required for rejection."}, status=status.HTTP_400_BAD_REQUEST)
        except AlreadyVotedError:
            return Response(
                {"error": "You have already voted on this change request."}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error("Unexpected error in reject: %s", str(e), exc_info=True)
            return Response(
                {"error": "An error occurred while processing rejection."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "status": result.status,
                "message": result.message,
                "change_request": ChangeRequestSerializer(result.change_request, context={"request": request}).data,
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
        service = ChangeRequestService(change_request, cast(User, request.user))

        try:
            result = service.cancel(reason=request.data.get("reason", "Canceled by requester"))
        except InvalidStateError:
            return Response(
                {"error": "This change request can no longer be canceled."}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error("Unexpected error in cancel: %s", str(e), exc_info=True)
            return Response(
                {"error": "An error occurred while canceling the request."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "status": result.status,
                "message": result.message,
                "change_request": ChangeRequestSerializer(result.change_request, context={"request": request}).data,
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

    def perform_create(self, serializer: BaseSerializer) -> None:
        serializer.save(
            created_by=self.request.user,
            organization=self.organization,
            team=self.team if hasattr(self, "team") else None,
        )

    def create(self, request: Request, *args, **kwargs) -> Response:
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError as e:
            if "posthog_approvalpolicy_organization_id_team_id" in str(e):
                raise exceptions.ValidationError(
                    "A policy for this action already exists. You can edit the existing policy instead."
                )
            raise
