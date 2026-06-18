from __future__ import annotations

from typing import cast

from django.db.models import QuerySet

import yaml
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import User
from posthog.permissions import AccessControlPermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from products.ai_observability.backend.models.parser_recipe import MAX_SOURCE_LENGTH, ParserRecipe


class ParserRecipeSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who created the recipe.",
    )

    class Meta:
        model = ParserRecipe
        fields = [
            "id",
            "name",
            "source",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]
        extra_kwargs = {
            "name": {"help_text": "Human-readable recipe name shown in the editor."},
            "source": {
                # Preserve the YAML verbatim
                "trim_whitespace": False,
                "max_length": MAX_SOURCE_LENGTH,
                "help_text": "Raw YAML recipe source. Must parse as YAML; recipe semantics are compiled and validated client-side.",
            },
        }

    def validate_source(self, value: str) -> str:
        # The DSL compiler only exists in the frontend; the API guarantees just the floor every
        # writer shares: parseable YAML. PyYAML raises RecursionError on deep nesting.
        try:
            yaml.safe_load(value)
        except (yaml.YAMLError, RecursionError) as e:
            raise serializers.ValidationError(f"Recipe source is not valid YAML: {e}")
        return value


class ParserRecipeViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    viewsets.ModelViewSet,
):
    scope_object = "llm_analytics"
    permission_classes = [IsAuthenticated, AccessControlPermission]
    serializer_class = ParserRecipeSerializer
    # Fail-closed manager raises if `.all()` runs at import; the real per-request
    # scoping happens in safely_get_queryset.
    queryset = ParserRecipe.objects.unscoped()
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset: QuerySet[ParserRecipe]) -> QuerySet[ParserRecipe]:
        return ParserRecipe.objects.for_team(self.team_id).select_related("created_by").order_by("created_at", "id")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        serializer.save(team=self.team, created_by=cast(User, self.request.user))
