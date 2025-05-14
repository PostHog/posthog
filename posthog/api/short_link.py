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
        fields = ["key", "destination_url", "created_at", "updated_at", "expiration_date"]
        read_only_fields = ["key", "created_at", "updated_at"]

    def create(self, validated_data: dict[str, Any]) -> ShortLink:
        team = self.context["team"]

        short_link = ShortLink.objects.create(
            team=team,
            destination_url=validated_data["destination_url"],
            expiration_date=validated_data.get("expiration_date"),
        )

        # Create a hashed version of the key for security lookups
        short_link.hashed_key = hashlib.sha256(short_link.key.encode()).hexdigest()
        short_link.save()

        logger.info("short_link_created", key=short_link.key, team_id=team.id)
        return short_link


class ShortLinkViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, read, update, and delete short links.
    """

    scope_object = "short_link"
    queryset = ShortLink.objects.all()
    serializer_class = ShortLinkSerializer
    lookup_field = "key"
    permission_classes = [IsAuthenticated]
    # Use the team from the user's current context when not in a team-specific route
    param_derived_from_user_current_team = "team_id"

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id).order_by("-created_at")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        logger.info("short_link_deleted", key=instance.key, team_id=self.team_id)
        return super().destroy(request, *args, **kwargs)


# Non-authenticated endpoint for redirecting short links
@cache_page(60 * 60 * 24)  # Cache for 24 hours
def short_link_redirect(request, key):
    """
    Public endpoint that redirects to the destination URL of a short link.
    """
    try:
        # Use hashed key for lookups if available
        hashed_key = hashlib.sha256(key.encode()).hexdigest()
        short_link = ShortLink.objects.filter(hashed_key=hashed_key).first()

        if not short_link:
            # Fall back to direct key lookup
            short_link = ShortLink.objects.get(key=key)

        # Check if link has expired
        if short_link.expiration_date and short_link.expiration_date < timezone.now():
            logger.info("short_link_expired", key=key)
            return HttpResponseNotFound("This short link has expired")

        logger.info("short_link_accessed", key=key, team_id=short_link.team_id)
        return HttpResponse(status=302, headers={"Location": short_link.destination_url})

    except ShortLink.DoesNotExist:
        logger.info("short_link_not_found", key=key)
        return HttpResponseNotFound("Short link not found")
