from __future__ import annotations

import json
from typing import Any

from django.db.models import Q, QuerySet

from rest_framework import mixins, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action

from products.conversations.backend.models import Macro, MacroVisibility
from products.conversations.backend.models.constants import Priority, Status

MAX_RICH_CONTENT_SIZE_BYTES = 100_000
MAX_ACTIONS_SIZE_BYTES = 10_000


class MacroAssigneeSerializer(serializers.Serializer):
    """Who a macro assigns the ticket to when applied."""

    type = serializers.CharField(help_text='Assignee kind: "user" or "role".')
    id = serializers.CharField(
        allow_null=True,
        help_text="User id (for type=user) or role id (for type=role). Null clears the assignee.",
    )


class MacroActionsSerializer(serializers.Serializer):
    """Optional ticket changes applied when a macro is used. Omit or leave empty for a text-only macro."""

    status = serializers.ChoiceField(
        choices=Status.choices,
        required=False,
        allow_null=True,
        help_text="Set the ticket status when the macro is applied.",
    )
    priority = serializers.ChoiceField(
        choices=Priority.choices,
        required=False,
        allow_null=True,
        help_text="Set the ticket priority when the macro is applied.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Replace the ticket's tags with this list when the macro is applied.",
    )
    assignee = MacroAssigneeSerializer(
        required=False,
        allow_null=True,
        help_text="Assign the ticket to this user or role when the macro is applied.",
    )


class MacroSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    name = serializers.CharField(max_length=200, help_text="Display name shown in the macro picker.")
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=400,
        help_text="Optional short description of when to use this macro.",
    )
    content = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Plain-text/markdown body of the reply. May contain {{variables}} filled in from the ticket.",
    )
    rich_content = serializers.JSONField(
        required=False,
        help_text="TipTap rich-content JSON for the reply body. Mirrors `content` with formatting preserved.",
    )
    actions = MacroActionsSerializer(
        required=False,
        help_text="Optional ticket changes (status, priority, tags, assignee) applied when the macro is used.",
    )
    visibility = serializers.ChoiceField(
        choices=MacroVisibility.choices,
        required=False,
        help_text='"team" shares the macro with everyone on the team; "personal" keeps it private to you.',
    )

    class Meta:
        model = Macro
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

    def create(self, validated_data: dict[str, Any]) -> Macro:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class MacroViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    # Reuse the "ticket" scope: macros are a support-agent tool and shouldn't grant access
    # beyond what ticket access already implies.
    scope_object = "ticket"
    # `safely_get_queryset` re-filters by team; the fail-closed manager can't run
    # `.all()` at class-definition time (no team context), so start unscoped.
    queryset = Macro.objects.unscoped().order_by("-created_at")
    serializer_class = MacroSerializer
    lookup_field = "short_id"

    def safely_get_queryset(self, queryset: QuerySet[Macro]) -> QuerySet[Macro]:
        queryset = queryset.filter(team_id=self.team_id).select_related("created_by")
        # Team macros are visible to everyone; personal macros only to their creator.
        return queryset.filter(
            Q(visibility=MacroVisibility.TEAM) | Q(visibility=MacroVisibility.PERSONAL, created_by=self.request.user)
        )

    def _track(self, event: str, instance: Macro) -> None:
        report_user_action(
            self.request.user,
            event,
            {
                "id": str(instance.id),
                "short_id": instance.short_id,
                "visibility": instance.visibility,
                "has_actions": bool(instance.actions),
            },
            team=self.team,
            request=self.request,
        )

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        self._track("conversations macro created", serializer.save())

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        self._track("conversations macro updated", serializer.save())

    def perform_destroy(self, instance: Macro) -> None:
        self._track("conversations macro deleted", instance)
        super().perform_destroy(instance)
