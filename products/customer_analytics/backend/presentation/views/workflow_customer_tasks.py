from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import AuthenticationFailed, NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication
from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.facade.workflow_customer_tasks import (
    WorkflowCustomerTaskOwnerInactive,
    WorkflowCustomerTaskProjectAccessDenied,
    WorkflowCustomerTasksDisabled,
    create_customer_task_from_workflow,
)
from products.workflows.backend.facade.api import WorkflowNotFound


class WorkflowCustomerTasksJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = ScopedServiceJwtPurpose(
        audience=PosthogJwtAudience.CUSTOMER_TASKS_CREATE,
        settings_name="CUSTOMER_ANALYTICS_ACCOUNTS_JWT_SECRETS",
    )


class WorkflowCustomerTaskCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=400, help_text="Task name.")
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, help_text="Task description."
    )
    account_id = serializers.UUIDField(required=False, allow_null=True, help_text="UUID of the linked account.")
    assigned_to_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=2147483647,
        help_text="PostHog user ID of the assigned project member.",
    )
    due_at = serializers.DateTimeField(required=False, allow_null=True, help_text="ISO 8601 task deadline.")
    idempotency_key = serializers.CharField(
        max_length=128, help_text="Invocation and action key from the workflow worker."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        unexpected = set(self.initial_data) - set(self.fields)
        if unexpected:
            raise serializers.ValidationError(dict.fromkeys(unexpected, "This field is not accepted."))
        return attrs


class WorkflowCustomerTaskResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="UUID of the created or previously created customer task.")


class WorkflowCustomerTaskViewSet(viewsets.GenericViewSet):
    authentication_classes = [WorkflowCustomerTasksJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowCustomerTaskCreateSerializer

    @extend_schema(
        request=WorkflowCustomerTaskCreateSerializer,
        responses={201: WorkflowCustomerTaskResponseSerializer},
        extensions={"x-product": "workflows"},
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        serializer = WorkflowCustomerTaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        idempotency_key = data.pop("idempotency_key")
        claims = cast(dict[str, Any], request.auth)
        if claims.get("idempotency_key") != idempotency_key:
            raise AuthenticationFailed("Service token does not grant access to this invocation.")
        try:
            workflow_id = UUID(str(claims.get("hog_flow_id")))
        except ValueError:
            raise AuthenticationFailed("Service token is missing its workflow claim.") from None
        team_id = cast(int, cast(InternalAPIUser, request.user).current_team_id)
        try:
            task_id = create_customer_task_from_workflow(
                team_id=team_id,
                workflow_id=workflow_id,
                idempotency_key=idempotency_key,
                input=contracts.CreateCustomerTaskInput(**data),
            )
        except WorkflowNotFound:
            raise NotFound("Workflow not found.") from None
        except WorkflowCustomerTaskOwnerInactive:
            raise PermissionDenied("Choose an active workflow owner before creating customer tasks.") from None
        except WorkflowCustomerTaskProjectAccessDenied:
            raise PermissionDenied("The workflow owner no longer has access to this project.") from None
        except WorkflowCustomerTasksDisabled:
            raise PermissionDenied("Enable customer tasks before using this workflow action.") from None
        except contracts.CustomerTaskAccessDenied:
            raise PermissionDenied(
                "The workflow owner needs editor access to customer tasks in the canonical project."
            ) from None
        except contracts.CustomerTaskAccountNotFound:
            raise NotFound("Account not found.") from None
        except (contracts.CustomerTaskAssigneeInvalid, contracts.CustomerTaskAssigneeCannotViewAccount):
            raise ValidationError(
                {"assigned_to_id": "Choose a project member who can access the linked account."}
            ) from None
        return Response(WorkflowCustomerTaskResponseSerializer({"id": task_id}).data, status=status.HTTP_201_CREATED)
