import hashlib
from typing import Any

from django.utils import timezone
from django.http import HttpResponse, HttpResponseNotFound
from django.views.decorators.cache import cache_page
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from django.db.models import QuerySet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import ShortLink
import structlog

logger = structlog.get_logger(__name__)


class ShortLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShortLink
        fields = ["id", "destination", "origin_domain", "origin_key", "description", "tags", "comments", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data: dict[str, Any]) -> ShortLink:
        team = self.context["team"]

        short_link = ShortLink.objects.create(
            team=team,
            destination=validated_data["destination"],
            origin_domain=validated_data["origin_domain"],
            origin_key=validated_data.get("origin_key"),
            description=validated_data.get("description"),
            tags=validated_data.get("tags"),
            comments=validated_data.get("comments"),
        )

        logger.info("short_link_created", id=short_link.id, team_id=team.id)
        return short_link


class ShortLinkViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, read, update, and delete short links.
    """

    scope_object = "short_link"
    queryset = ShortLink.objects.all()
    serializer_class = ShortLinkSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticated]
    # Use the team from the user's current context when not in a team-specific route
    param_derived_from_user_current_team = "team_id"

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id).order_by("-created_at")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        logger.info("short_link_deleted", id=instance.id, team_id=self.team_id)
        return super().destroy(request, *args, **kwargs)


# Non-authenticated endpoint for redirecting short links
@cache_page(60 * 60 * 24)  # Cache for 24 hours
def short_link_redirect(request, id):
    """
    Public endpoint that redirects to the destination URL of a short link.
    """
    try:
        short_link = ShortLink.objects.get(id=id)

        logger.info("short_link_accessed", id=id, team_id=short_link.team_id)
        return HttpResponse(status=302, headers={"Location": short_link.destination})

    except ShortLink.DoesNotExist:
        logger.info("short_link_not_found", id=id)
        return HttpResponseNotFound("Short link not found")
