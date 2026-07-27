from __future__ import annotations

import json
from typing import Any

from django.db.models import Q, QuerySet

from rest_framework import mixins, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action

from products.conversations.backend.models import QuickAction, QuickActionVisibility
from products.conversations.backend.models.constants import Priority, Status

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

        # A quick action must do something: insert a reply or apply ticket actions.
        has_reply = bool(self._effective(attrs, "content") or self._effective(attrs, "rich_content"))
        has_actions = bool(self._effective(attrs, "actions"))
        if not (has_reply or has_actions):
            raise serializers.ValidationError("A quick action needs a reply or a ticket action.")

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
    scope_object_write_actions = ["create", "update", "partial_update", "patch", "destroy"]
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
