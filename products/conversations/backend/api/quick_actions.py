from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from requests.exceptions import RequestException
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action

from products.conversations.backend.events import (
    _get_assignment_properties,
    _get_customer_properties,
    _get_ticket_base_properties,
    _groups_from_org_id,
    _resolve_org_groups,
)
from products.conversations.backend.models import QuickAction, QuickActionVisibility, Ticket
from products.conversations.backend.models.constants import Priority, Status
from products.workflows.backend.facade.api import (
    HogFlowNotRunnableError,
    invoke_hog_flow_now,
    user_can_run_workflow,
    workflow_is_runnable,
)

logger = structlog.get_logger(__name__)

MAX_RICH_CONTENT_SIZE_BYTES = 100_000
MAX_ACTIONS_SIZE_BYTES = 10_000
MAX_CONTENT_SIZE_CHARS = 50_000


class QuickActionAssigneeSerializer(serializers.Serializer):
    """Who a quick action assigns the ticket to when applied."""

    type = serializers.ChoiceField(choices=["user", "role"], help_text='Assignee kind: "user" or "role".')
    id = serializers.CharField(
        allow_null=True,
        help_text="User id (for type=user) or role id (for type=role). Null clears the assignee.",
    )


class QuickActionActionsSerializer(serializers.Serializer):
    """Optional ticket changes applied when a response quick action is used. Omit for text-only."""

    status = serializers.ChoiceField(
        choices=Status.choices,
        required=False,
        allow_null=True,
        help_text="Set the ticket status when the quick action is applied.",
    )
    priority = serializers.ChoiceField(
        choices=Priority.choices,
        required=False,
        allow_null=True,
        help_text="Set the ticket priority when the quick action is applied.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Replace the ticket's tags with this list when the quick action is applied.",
    )
    assignee = QuickActionAssigneeSerializer(
        required=False,
        allow_null=True,
        help_text="Assign the ticket to this user or role when the quick action is applied.",
    )


class QuickActionSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    name = serializers.CharField(max_length=200, help_text="Display name shown in the quick action picker.")
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=400,
        help_text="Optional short description of when to use this quick action.",
    )
    content = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=MAX_CONTENT_SIZE_CHARS,
        help_text="Reply body (plain-text/markdown). May contain {{variables}} filled in from the ticket.",
    )
    rich_content = serializers.JSONField(
        required=False,
        help_text="TipTap rich-content JSON for the reply body. Mirrors `content` with formatting preserved.",
    )
    actions = QuickActionActionsSerializer(
        required=False,
        help_text="Ticket changes (status, priority, tags, assignee) applied when the quick action is used.",
    )
    workflow_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional: id of a workflow to run against the ticket when the quick action is used.",
    )
    visibility = serializers.ChoiceField(
        choices=QuickActionVisibility.choices,
        required=False,
        help_text='"team" shares with everyone on the team; "personal" keeps it private to you.',
    )

    class Meta:
        model = QuickAction
        fields = [
            "id",
            "short_id",
            "name",
            "description",
            "content",
            "rich_content",
            "actions",
            "workflow_id",
            "visibility",
            "created_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "short_id",
            "created_at",
            "created_by",
        ]

    def validate_rich_content(self, value: object) -> object:
        try:
            serialized = json.dumps(value)
        except (TypeError, ValueError) as e:
            raise serializers.ValidationError("Rich content must be JSON-serializable.") from e
        if len(serialized) > MAX_RICH_CONTENT_SIZE_BYTES:
            raise serializers.ValidationError("Rich content too large (max 100KB).")
        return value

    def validate_actions(self, value: dict) -> dict:
        if len(json.dumps(value)) > MAX_ACTIONS_SIZE_BYTES:
            raise serializers.ValidationError("Actions payload is too large.")
        return value

    def _effective(self, attrs: dict[str, Any], field: str) -> Any:
        """Value after this write: the incoming value if present, else the instance's (for PATCH)."""
        if field in attrs:
            return attrs[field]
        return getattr(self.instance, field, None)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        instance = self.instance

        # A quick action must do something: insert a reply, apply ticket actions, or run a workflow.
        has_reply = bool(self._effective(attrs, "content") or self._effective(attrs, "rich_content"))
        has_actions = bool(self._effective(attrs, "actions"))
        workflow_id = self._effective(attrs, "workflow_id")
        if not (has_reply or has_actions or workflow_id):
            raise serializers.ValidationError("A quick action needs a reply, a ticket action, or a workflow to run.")

        # If it runs a workflow, that workflow must be active for the team.
        if workflow_id and not workflow_is_runnable(self.context["team_id"], workflow_id):
            raise serializers.ValidationError({"workflow_id": "That workflow does not exist or is not active."})

        # RBAC: attaching a workflow requires access to that workflow — otherwise a ticket-scoped
        # user could wire up (and later run) privileged automations by UUID. Only checked when the
        # reference is being set/changed, so unrelated edits by teammates without workflow access
        # don't get blocked. The run endpoint re-checks the actual runner at execution time.
        if attrs.get("workflow_id") and not user_can_run_workflow(
            self.context["request"].user, self.context["get_team"](), attrs["workflow_id"]
        ):
            raise serializers.ValidationError({"workflow_id": "You don't have access to that workflow."})

        # Only the creator may turn a shared team quick action personal — otherwise a teammate's
        # edit would make it vanish for everyone else (and the editor), with no way to reach it again.
        if (
            instance is not None
            and attrs.get("visibility") == QuickActionVisibility.PERSONAL
            and instance.visibility == QuickActionVisibility.TEAM
            and instance.created_by_id != self.context["request"].user.id
        ):
            raise serializers.ValidationError(
                {"visibility": "Only the creator can make a shared team quick action personal."}
            )
        return attrs

    def update(self, instance: QuickAction, validated_data: dict[str, Any]) -> QuickAction:
        # `actions` is a single JSON column, so DRF replaces it wholesale. The Settings UI has no
        # assignee control, so merge the existing assignee back in to avoid silently dropping one
        # set via the API. Status/priority/tags stay full-replace so clearing them in the UI sticks.
        if "actions" in validated_data:
            new_actions = validated_data["actions"] or {}
            if "assignee" not in new_actions and instance.actions.get("assignee"):
                new_actions = {**new_actions, "assignee": instance.actions["assignee"]}
            validated_data["actions"] = new_actions
        return super().update(instance, validated_data)

    def create(self, validated_data: dict[str, Any]) -> QuickAction:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class QuickActionRunRequestSerializer(serializers.Serializer):
    ticket_id = serializers.UUIDField(help_text="Ticket to run the workflow against.")


def _build_ticket_event_globals(ticket: Ticket) -> dict:
    """Synthesize the event/globals payload a workflow receives, mirroring the shape of the
    `$conversation_*` events in events.py so workflow filters and ticket actions see the ticket."""
    properties: dict[str, Any] = {}
    properties.update(_get_ticket_base_properties(ticket))
    properties.update(_get_customer_properties(ticket, include_distinct_id=True))
    properties.update(_get_assignment_properties(ticket))
    try:
        # Fast path: reuse the org id already resolved onto the ticket, like events.py does, instead
        # of paying for the full person-lookup resolver on every run.
        if ticket.organization_id:
            properties["$groups"] = _groups_from_org_id(ticket.team, ticket.organization_id)
        else:
            _, groups, _ = _resolve_org_groups(ticket, ticket.team)
            if groups is not None:
                properties["$groups"] = groups
    except Exception:
        logger.exception("quick_action_run_group_resolution_failed", ticket_id=str(ticket.id))
    return {
        "event": {
            "event": "$conversation_quick_action_triggered",
            "properties": properties,
            "distinct_id": ticket.distinct_id or ticket.channel_source or "unknown",
            "timestamp": timezone.now().isoformat(),
        },
        "groups": properties.get("$groups"),
    }


class QuickActionViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    # Reuse the "ticket" scope: quick actions are a support-agent tool and shouldn't grant access
    # beyond what ticket access already implies.
    scope_object = "ticket"
    # Custom @action methods fall through to no required scope unless listed here, which 403s every
    # personal-API-key / MCP caller. Keep the DRF defaults and add `run`.
    scope_object_write_actions = ["create", "update", "partial_update", "patch", "destroy", "run"]
    # `safely_get_queryset` re-filters by team; the fail-closed manager can't run `.all()` at
    # class-definition time (no team context), so start unscoped.
    queryset = QuickAction.objects.unscoped().order_by("-created_at")
    serializer_class = QuickActionSerializer
    lookup_field = "short_id"

    def safely_get_queryset(self, queryset: QuerySet[QuickAction]) -> QuerySet[QuickAction]:
        # `for_team` resolves child environments to the canonical (parent) team id, matching the
        # rewrite `RootTeamMixin.save()` performs on write. Filtering by the raw `self.team_id`
        # would miss quick actions created in a child environment (stored under the parent).
        queryset = QuickAction.objects.for_team(self.team_id).select_related("created_by")
        # Team quick actions are visible to everyone; personal ones only to their creator.
        return queryset.filter(
            Q(visibility=QuickActionVisibility.TEAM)
            | Q(visibility=QuickActionVisibility.PERSONAL, created_by=self.request.user)
        )

    def _track(self, event: str, instance: QuickAction) -> None:
        report_user_action(
            self.request.user,
            event,
            {
                "id": str(instance.id),
                "short_id": instance.short_id,
                "visibility": instance.visibility,
                "has_reply": bool(instance.content or instance.rich_content),
                "has_actions": bool(instance.actions),
                "has_workflow": bool(instance.workflow_id),
            },
            team=self.team,
            request=self.request,
        )

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        self._track("conversations quick action created", serializer.save())

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        self._track("conversations quick action updated", serializer.save())

    def perform_destroy(self, instance: QuickAction) -> None:
        self._track("conversations quick action deleted", instance)
        super().perform_destroy(instance)

    @extend_schema(
        request=QuickActionRunRequestSerializer,
        responses={202: OpenApiResponse(description="Workflow run enqueued.")},
    )
    @action(detail=True, methods=["post"])
    def run(self, request: Request, **kwargs: Any) -> Response:
        """Run a workflow quick action against a ticket, synthesizing the ticket's event context."""
        quick_action = self.get_object()
        if not quick_action.workflow_id:
            raise serializers.ValidationError({"workflow_id": "This quick action does not run a workflow."})

        # RBAC: the runner (not the quick action's creator) must have access to the workflow —
        # a shared quick action must not let a ticket-scoped user execute a workflow they can't
        # operate, since workflows run privileged actions with their stored secrets.
        if not user_can_run_workflow(request.user, self.team, quick_action.workflow_id):  # type: ignore[arg-type]
            raise PermissionDenied("You don't have access to the workflow this quick action runs.")

        request_serializer = QuickActionRunRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        ticket_id: UUID = request_serializer.validated_data["ticket_id"]
        ticket = Ticket.objects.filter(team_id=self.team_id, id=ticket_id).select_related("team").first()
        if ticket is None:
            raise serializers.ValidationError({"ticket_id": "Ticket not found."})

        globals_payload = _build_ticket_event_globals(ticket)
        try:
            invoke_hog_flow_now(self.team_id, quick_action.workflow_id, globals_payload)
        except HogFlowNotRunnableError as e:
            raise serializers.ValidationError({"workflow_id": str(e)})
        except RequestException:
            # The workflow service (CDP) was unreachable — a transient upstream failure, not a bad
            # request. Surface a clean 502 rather than an unhandled 500.
            logger.exception("quick_action_run_workflow_service_unreachable", workflow_id=str(quick_action.workflow_id))
            return Response(
                {"detail": "Couldn't reach the workflow service. Try again shortly."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        self._track("conversations quick action run", quick_action)
        return Response(status=status.HTTP_202_ACCEPTED)
