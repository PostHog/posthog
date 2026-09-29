from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed, NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication
from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.facade.enums import CustomerTaskAgentOutcome
from products.customer_analytics.backend.facade.workflow_customer_tasks import (
    WorkflowCustomerTaskOwnerInactive,
    WorkflowCustomerTaskProjectAccessDenied,
    WorkflowCustomerTasksDisabled,
    WorkflowCustomerTaskWorkflowMismatch,
    create_customer_task_from_workflow,
    report_customer_task_from_workflow,
)
from products.workflows.backend.facade.api import WorkflowNotFound


class WorkflowCustomerTasksJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = ScopedServiceJwtPurpose(
        audience=PosthogJwtAudience.CUSTOMER_TASKS_CREATE,
        settings_name="CUSTOMER_ANALYTICS_ACCOUNTS_JWT_SECRETS",
    )


class WorkflowCustomerTasksReportJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = ScopedServiceJwtPurpose(
        audience=PosthogJwtAudience.CUSTOMER_TASKS_REPORT,
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


class WorkflowCustomerTaskReportSerializer(serializers.Serializer):
    report = serializers.CharField(max_length=50_000, help_text="What the agent did and what is left for a person.")
    outcome = serializers.ChoiceField(
        choices=CustomerTaskAgentOutcome.choices,
        help_text="completed closes the task. needs_human hands it back to the person who assigned PostHog.",
    )
    task_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=128,
        help_text="The AI task that did the work, kept in the activity log.",
    )
    task_run_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=128,
        help_text="The run that did the work, kept in the activity log.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        unexpected = set(self.initial_data) - set(self.fields)
        if unexpected:
            raise serializers.ValidationError(dict.fromkeys(unexpected, "This field is not accepted."))
        return attrs


class WorkflowCustomerTaskResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="UUID of the customer task.")


class WorkflowCustomerTaskConflictSerializer(serializers.Serializer):
    detail = serializers.CharField(read_only=True, help_text="Why the task cannot take the report.")


def _workflow_id_from_claims(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims.get("hog_flow_id")))
    except ValueError:
        raise AuthenticationFailed("Service token is missing its workflow claim.") from None


def _owner_gate_error(exc: Exception) -> PermissionDenied | NotFound | None:
    if isinstance(exc, WorkflowNotFound):
        return NotFound("Workflow not found.")
    if isinstance(exc, WorkflowCustomerTaskOwnerInactive):
        return PermissionDenied("Choose an active workflow owner before using this workflow action.")
    if isinstance(exc, WorkflowCustomerTaskProjectAccessDenied):
        return PermissionDenied("The workflow owner no longer has access to this project.")
    if isinstance(exc, WorkflowCustomerTasksDisabled):
        return PermissionDenied("Enable customer tasks before using this workflow action.")
    return None


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
        workflow_id = _workflow_id_from_claims(claims)
        team_id = cast(int, cast(InternalAPIUser, request.user).current_team_id)
        try:
            task_id = create_customer_task_from_workflow(
                team_id=team_id,
                workflow_id=workflow_id,
                idempotency_key=idempotency_key,
                input=contracts.CreateCustomerTaskInput(**data),
            )
        except (
            WorkflowNotFound,
            WorkflowCustomerTaskOwnerInactive,
            WorkflowCustomerTaskProjectAccessDenied,
            WorkflowCustomerTasksDisabled,
        ) as exc:
            raise cast(Exception, _owner_gate_error(exc)) from None
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

    @extend_schema(
        request=WorkflowCustomerTaskReportSerializer,
        responses={
            200: WorkflowCustomerTaskResponseSerializer,
            409: WorkflowCustomerTaskConflictSerializer,
        },
        extensions={"x-product": "workflows"},
    )
    @action(detail=True, methods=["post"], authentication_classes=[WorkflowCustomerTasksReportJWTAuthentication])
    def report(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        serializer = WorkflowCustomerTaskReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            task_id = UUID(str(pk))
        except ValueError:
            raise NotFound("Customer task not found.") from None
        claims = cast(dict[str, Any], request.auth)
        # The worker pins the token to the one task its step names, so a token that leaks from a
        # run cannot report to any other task before it expires.
        if str(claims.get("customer_task_id", "")).lower() != str(task_id):
            raise AuthenticationFailed("Service token does not grant access to this task.")
        idempotency_key = claims.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise AuthenticationFailed("Service token is missing its invocation claim.")
        workflow_id = _workflow_id_from_claims(claims)
        team_id = cast(int, cast(InternalAPIUser, request.user).current_team_id)
        try:
            report_customer_task_from_workflow(
                team_id=team_id,
                workflow_id=workflow_id,
                task_id=task_id,
                idempotency_key=idempotency_key,
                input=contracts.ReportCustomerTaskInput(
                    report=data["report"],
                    outcome=data["outcome"],
                    task_id=data.get("task_id") or None,
                    task_run_id=data.get("task_run_id") or None,
                ),
            )
        except (
            WorkflowNotFound,
            WorkflowCustomerTaskOwnerInactive,
            WorkflowCustomerTaskProjectAccessDenied,
            WorkflowCustomerTasksDisabled,
        ) as exc:
            raise cast(Exception, _owner_gate_error(exc)) from None
        except contracts.CustomerTaskNotFound:
            raise NotFound("Customer task not found.") from None
        except contracts.CustomerTaskAccessDenied:
            raise PermissionDenied("The workflow owner needs editor access to this task.") from None
        except WorkflowCustomerTaskWorkflowMismatch:
            raise PermissionDenied("Another workflow is assigned to this task.") from None
        except contracts.CustomerTaskArchived:
            error = WorkflowCustomerTaskConflictSerializer(
                instance={"detail": "Restore this task before reporting to it."}
            )
            return Response(error.data, status=status.HTTP_409_CONFLICT)
        return Response(WorkflowCustomerTaskResponseSerializer({"id": task_id}).data)
