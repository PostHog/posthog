from __future__ import annotations

from typing import Any, cast

from django.db.models import QuerySet

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission, TeamMemberAccessPermission

from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.customer_analytics.backend.facade import contracts, tasks
from products.customer_analytics.backend.facade.constants import CUSTOMER_ANALYTICS_CUSTOMER_TASKS_FLAG
from products.customer_analytics.backend.models import CustomerTask

_TASK_STATUS_CHOICES = [(value, value) for value in ("open", "in_progress", "completed", "canceled")]
_ORDERING_CHOICES = [
    "due_at",
    "-due_at",
    "created_at",
    "-created_at",
    "updated_at",
    "-updated_at",
    "name",
    "-name",
]


class CustomerTaskUserSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True, help_text="PostHog user ID.")
    email = serializers.EmailField(read_only=True, help_text="Email address of the user.")
    first_name = serializers.CharField(read_only=True, help_text="First name of the user.")
    last_name = serializers.CharField(read_only=True, help_text="Last name of the user.")


class CustomerTaskAccountSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="UUID of the linked account.")
    name = serializers.CharField(read_only=True, help_text="Name of the linked account.")


class CustomerTaskSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="UUID of the task.")
    account = CustomerTaskAccountSerializer(read_only=True, allow_null=True, help_text="Linked account, if any.")
    name = serializers.CharField(read_only=True, help_text="Task name.")
    description = serializers.CharField(read_only=True, allow_null=True, help_text="Task description, if any.")
    status = serializers.ChoiceField(read_only=True, choices=_TASK_STATUS_CHOICES, help_text="Task lifecycle status.")
    assigned_to = CustomerTaskUserSerializer(
        read_only=True, allow_null=True, help_text="Assigned project member, if any."
    )
    due_at = serializers.DateTimeField(read_only=True, allow_null=True, help_text="Task deadline, if any.")
    completed_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the task was completed, if applicable."
    )
    completed_by = CustomerTaskUserSerializer(
        read_only=True, allow_null=True, help_text="User credited with completion, if known."
    )
    created_by = CustomerTaskUserSerializer(
        read_only=True, allow_null=True, help_text="User who created the task, if known."
    )
    archived_at = serializers.DateTimeField(read_only=True, allow_null=True, help_text="When the task was archived.")
    created_at = serializers.DateTimeField(read_only=True, help_text="When the task was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the task was last updated.")
    can_edit = serializers.BooleanField(read_only=True, help_text="Whether the current user can edit this task.")


class CustomerTaskCreateSerializer(serializers.Serializer):
    account_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="UUID of a visible account, or null for an accountless task."
    )
    name = serializers.CharField(max_length=400, error_messages={"blank": "Enter a task name."}, help_text="Task name.")
    description = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, help_text="Task description, or null to leave it empty."
    )
    assigned_to_id = serializers.IntegerField(
        required=False, allow_null=True, help_text="PostHog user ID to assign, or null to leave unassigned."
    )
    due_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="ISO 8601 deadline, or null for no deadline."
    )
    status = serializers.ChoiceField(
        required=False, default="open", choices=_TASK_STATUS_CHOICES, help_text="Initial task status."
    )

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter a task name.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        unexpected = set(self.initial_data) - set(self.fields)
        if unexpected:
            raise serializers.ValidationError(dict.fromkeys(unexpected, "This field is not accepted."))
        return attrs


class CustomerTaskUpdateSerializer(serializers.Serializer):
    account_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="UUID of a visible account, or null to remove the account link."
    )
    name = serializers.CharField(
        max_length=400,
        allow_null=False,
        error_messages={"blank": "Enter a task name."},
        help_text="Replacement task name.",
    )
    description = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, help_text="Replacement description, or null to clear it."
    )
    assigned_to_id = serializers.IntegerField(
        required=False, allow_null=True, help_text="Replacement assignee ID, or null to unassign."
    )
    due_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="Replacement ISO 8601 deadline, or null to clear it."
    )
    status = serializers.ChoiceField(
        required=False, allow_null=False, choices=_TASK_STATUS_CHOICES, help_text="Replacement task status."
    )

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter a task name.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        unexpected = set(self.initial_data) - set(self.fields)
        if unexpected:
            raise serializers.ValidationError(dict.fromkeys(unexpected, "This field is not accepted."))
        return attrs


@extend_schema_field({"oneOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}, {"type": "object"}]})
class CustomerTaskChangeValueField(serializers.JSONField):
    pass


class CustomerTaskChangeSerializer(serializers.Serializer):
    field = serializers.CharField(read_only=True, help_text="Semantic task field that changed.")
    before = CustomerTaskChangeValueField(read_only=True, allow_null=True, help_text="Value before the change.")
    after = CustomerTaskChangeValueField(read_only=True, allow_null=True, help_text="Value after the change.")


class CustomerTaskActivitySerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="UUID of the activity.")
    activity_type = serializers.ChoiceField(
        read_only=True,
        choices=[(value, value) for value in ("created", "updated", "archived", "restored")],
        help_text="Action that produced the activity.",
    )
    changes = CustomerTaskChangeSerializer(
        many=True, read_only=True, help_text="Semantic field changes in this action."
    )
    actor = CustomerTaskUserSerializer(read_only=True, allow_null=True, help_text="User who made the change, if known.")
    created_at = serializers.DateTimeField(read_only=True, help_text="When the activity was recorded.")


class CustomerTaskListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True, help_text="Search task name and description.")
    account_id = serializers.UUIDField(required=False, help_text="Filter by account UUID.")
    assigned_to = serializers.CharField(required=False, help_text="Filter by me, unassigned, or one user ID.")
    statuses = serializers.CharField(required=False, help_text="Comma-separated task statuses.")
    archive_state = serializers.ChoiceField(
        required=False,
        default="active",
        choices=[("active", "active"), ("archived", "archived"), ("all", "all")],
        help_text="Which archive state to include.",
    )
    due_after = serializers.DateTimeField(required=False, help_text="Inclusive lower deadline bound.")
    due_before = serializers.DateTimeField(required=False, help_text="Exclusive upper deadline bound.")
    has_due_at = serializers.BooleanField(required=False, help_text="Filter tasks by whether a deadline exists.")
    ordering = serializers.ChoiceField(
        required=False, choices=[(value, value) for value in _ORDERING_CHOICES], help_text="Task ordering."
    )
    limit = serializers.IntegerField(
        required=False, default=50, min_value=0, max_value=100, help_text="Page size, up to 100."
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0, help_text="Number of rows to skip.")

    def validate_assigned_to(self, value: str) -> str:
        if value not in {"me", "unassigned"} and not value.isdigit():
            raise serializers.ValidationError("assigned_to must be me, unassigned, or a project member ID.")
        return value

    def validate_statuses(self, value: str) -> tuple[str, ...]:
        values = tuple(part.strip() for part in value.split(","))
        if not values or any(part not in dict(_TASK_STATUS_CHOICES) for part in values):
            raise serializers.ValidationError("statuses must contain only open, in_progress, completed, or canceled.")
        return values


class CustomerTaskActivityQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        required=False, default=50, min_value=0, max_value=100, help_text="Page size, up to 100."
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0, help_text="Number of rows to skip.")


class CustomerTaskPagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 100


def _paginated_response(
    request: Request,
    page: list[Any],
    count: int,
    limit: int,
    offset: int,
    serializer_class: type[serializers.Serializer],
) -> Response:
    paginator = CustomerTaskPagination()
    paginator.request = request
    paginator.limit = limit
    paginator.offset = offset
    paginator.count = count
    return paginator.get_paginated_response(serializer_class(instance=page, many=True).data)


class CustomerTaskPermission(BasePermission):
    message = "You do not have access to this customer task."

    def has_permission(self, request: Request, view: CustomerTaskViewSet) -> bool:
        if view.action == "create" and not view.user_access_control.check_access_level_for_resource(
            "customer_task", "editor"
        ):
            self.message = "You need editor access to Customer Tasks to create a task."
            return False
        return True

    def has_object_permission(self, request: Request, view: CustomerTaskViewSet, obj: CustomerTask) -> bool:
        return tasks.can_access_customer_task_object(
            task=obj,
            user_access_control=view.user_access_control,
            write=request.method not in {"GET", "HEAD", "OPTIONS"},
        )


class CustomerTaskViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.GenericViewSet):
    scope_object = "customer_task"
    serializer_class = CustomerTaskSerializer
    queryset = CustomerTask.objects.unscoped()
    posthog_feature_flag = CUSTOMER_ANALYTICS_CUSTOMER_TASKS_FLAG
    scope_object_read_actions = ["list", "retrieve", "activities"]
    scope_object_write_actions = ["create", "update", "partial_update", "archive", "restore"]
    permission_classes = [PostHogFeatureFlagPermission, CustomerTaskPermission]

    def dangerously_get_permissions(self) -> list[BasePermission]:
        return [
            IsAuthenticated(),
            APIScopePermission(),
            TeamMemberAccessPermission(),
            PostHogFeatureFlagPermission(),
            CustomerTaskPermission(),
        ]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id)

    def safely_get_object(self, queryset: QuerySet) -> CustomerTask | None:
        return (
            queryset.filter(pk=self.kwargs["pk"])
            .select_related("account", "assigned_to", "completed_by", "created_by")
            .first()
        )

    @validated_request(
        query_serializer=CustomerTaskListQuerySerializer,
        responses={200: OpenApiResponse(response=CustomerTaskSerializer(many=True))},
    )
    def list(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        data = request.validated_query_data
        page, count = tasks.list_customer_tasks(
            team_id=self.team_id,
            user_access_control=self.user_access_control,
            filters=contracts.CustomerTaskListFilters(
                search=data.get("search", "").strip() or None,
                account_id=data.get("account_id"),
                assigned_to=data.get("assigned_to"),
                statuses=data.get("statuses", ()),
                archive_state=data["archive_state"],
                due_after=data.get("due_after"),
                due_before=data.get("due_before"),
                has_due_at=data.get("has_due_at"),
                ordering=data.get("ordering"),
            ),
            offset=data["offset"],
            limit=data["limit"],
        )
        return _paginated_response(request, page, count, data["limit"], data["offset"], CustomerTaskSerializer)

    @extend_schema(responses={200: CustomerTaskSerializer, 404: OpenApiResponse(description="Task not found.")})
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        task = tasks.get_customer_task(
            team_id=self.team_id, task_id=self.kwargs["pk"], user_access_control=self.user_access_control
        )
        if task is None:
            return Response({"detail": "Task not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomerTaskSerializer(instance=task).data)

    @extend_schema(request=CustomerTaskCreateSerializer, responses={201: CustomerTaskSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = CustomerTaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = tasks.create_customer_task(
            team=self.team,
            input=contracts.CreateCustomerTaskInput(**serializer.validated_data),
            actor=cast(User, request.user),
            user_access_control=self.user_access_control,
        )
        return Response(CustomerTaskSerializer(instance=task).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=CustomerTaskUpdateSerializer, responses={200: CustomerTaskSerializer})
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = CustomerTaskUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if not request.data:
            raise ValidationError({"detail": "Change at least one task field."})
        data = serializer.validated_data
        task = tasks.update_customer_task(
            team=self.team,
            task_id=self.kwargs["pk"],
            input=contracts.UpdateCustomerTaskInput(
                **data,
                account_id_provided="account_id" in request.data,
                name_provided="name" in request.data,
                description_provided="description" in request.data,
                assigned_to_id_provided="assigned_to_id" in request.data,
                due_at_provided="due_at" in request.data,
                status_provided="status" in request.data,
            ),
            actor=cast(User, request.user),
            user_access_control=self.user_access_control,
        )
        if task is None:
            return Response({"detail": "Task not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomerTaskSerializer(instance=task).data)

    @extend_schema(responses={200: CustomerTaskSerializer})
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.partial_update(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    @extend_schema(request=None, responses={200: CustomerTaskSerializer})
    def archive(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        task = tasks.archive_customer_task(
            team_id=self.team_id,
            task_id=self.kwargs["pk"],
            actor=cast(User, request.user),
            user_access_control=self.user_access_control,
        )
        if task is None:
            return Response({"detail": "Task not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomerTaskSerializer(instance=task).data)

    @action(detail=True, methods=["post"])
    @extend_schema(request=None, responses={200: CustomerTaskSerializer})
    def restore(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        task = tasks.restore_customer_task(
            team_id=self.team_id,
            task_id=self.kwargs["pk"],
            actor=cast(User, request.user),
            user_access_control=self.user_access_control,
        )
        if task is None:
            return Response({"detail": "Task not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomerTaskSerializer(instance=task).data)

    @action(detail=True, methods=["get"])
    @validated_request(
        query_serializer=CustomerTaskActivityQuerySerializer,
        responses={200: OpenApiResponse(response=CustomerTaskActivitySerializer(many=True))},
    )
    def activities(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        data = request.validated_query_data
        result = tasks.list_customer_task_activities(
            team_id=self.team_id,
            task_id=self.kwargs["pk"],
            user_access_control=self.user_access_control,
            offset=data["offset"],
            limit=data["limit"],
        )
        if result is None:
            return Response({"detail": "Task not found."}, status=status.HTTP_404_NOT_FOUND)
        page, count = result
        return _paginated_response(request, page, count, data["limit"], data["offset"], CustomerTaskActivitySerializer)

    def handle_exception(self, exc: Exception) -> Response | None:
        if isinstance(exc, tasks.CustomerTaskAccountNotFound):
            return Response({"detail": "Account not found."}, status=status.HTTP_404_NOT_FOUND)
        if isinstance(exc, tasks.CustomerTaskAssigneeInvalid):
            return Response({"assigned_to_id": "Select a member of this project."}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(exc, tasks.CustomerTaskAssigneeCannotViewAccount):
            return Response(
                {
                    "assigned_to_id": "This person can"
                    + chr(39)
                    + "t access the selected account. Choose another assignee or remove the account link."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if isinstance(exc, tasks.CustomerTaskInvalidTransition):
            return Response(
                {"status": "This task can" + chr(39) + f"t move from {exc.current} to {exc.requested}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if isinstance(exc, tasks.CustomerTaskAccessDenied):
            return Response(
                {"detail": "You do not have editor access to this customer task."}, status=status.HTTP_403_FORBIDDEN
            )
        if isinstance(exc, tasks.CustomerTaskArchived):
            return Response({"detail": "Restore this task before editing it."}, status=status.HTTP_409_CONFLICT)
        return super().handle_exception(exc)
