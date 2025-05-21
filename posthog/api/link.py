from typing import Any

from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from django.db.models import QuerySet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import Link
import structlog

from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)


class LinkSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    short_code = serializers.CharField(required=True, allow_null=False)

    class Meta:
        model = Link
        fields = [
            "id",
            "redirect_url",
            "short_link_domain",
            "short_code",
            "description",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data: dict[str, Any]) -> Link:
        team = Team.objects.get(id=self.context["team_id"])

        if validated_data.get("short_link_domain") != "phog.gg":
            raise serializers.ValidationError({"short_link_domain": "Only phog.gg is allowed as a short link domain"})

        link = Link.objects.create(
            team=team,
            redirect_url=validated_data["redirect_url"],
            short_link_domain=validated_data["short_link_domain"],
            short_code=validated_data["short_code"],
            description=validated_data.get("description"),
            created_by=self.context["request"].user,
        )

        logger.info("link_created", id=link.id, team_id=team.id)
        return link


class LinkViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, read, update, and delete links.
    """

    scope_object = "link"
    queryset = Link.objects.all()
    serializer_class = LinkSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticated]
    # Use the team from the user's current context when not in a team-specific route
    param_derived_from_user_current_team = "team_id"

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id).order_by("-created_at")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        logger.info("link_deleted", id=instance.id, team_id=self.team_id)
        return super().destroy(request, *args, **kwargs)
