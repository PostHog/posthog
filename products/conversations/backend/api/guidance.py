from django.db.models import QuerySet

import structlog
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.conversations.backend.models import GuidanceRule

logger = structlog.get_logger(__name__)


class GuidanceRuleSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = GuidanceRule
        fields = [
            "id",
            "rule_type",
            "name",
            "content",
            "is_active",
            "channels",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def create(self, validated_data):
        """Set created_by to current user."""
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class GuidanceRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "guidance_rule"
    queryset = GuidanceRule.objects.all()
    serializer_class = GuidanceRuleSerializer
    permission_classes = [IsAuthenticated]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        """Filter rules by team."""
        queryset = queryset.filter(team_id=self.team_id)

        # Filter by is_active if provided
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == "true")

        # Filter by rule_type if provided
        rule_type = self.request.query_params.get("rule_type")
        if rule_type:
            queryset = queryset.filter(rule_type=rule_type)

        # Search by name if provided
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__icontains=search)

        return queryset.order_by("-created_at")
