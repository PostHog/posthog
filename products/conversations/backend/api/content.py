from django.db.models import QuerySet

import structlog
from rest_framework import pagination, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.conversations.backend.models import ContentArticle

logger = structlog.get_logger(__name__)


class ContentArticlePagination(pagination.LimitOffsetPagination):
    default_limit = 100
    max_limit = 1000


class ContentArticleSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = ContentArticle
        fields = [
            "id",
            "title",
            "body",
            "is_enabled",
            "channels",
            "embeddings",
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


class ContentArticleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "content_article"
    queryset = ContentArticle.objects.all()
    serializer_class = ContentArticleSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = ContentArticlePagination

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        """Filter articles by team."""
        queryset = queryset.filter(team_id=self.team_id)

        # Filter by is_enabled if provided
        is_enabled = self.request.query_params.get("is_enabled")
        if is_enabled is not None:
            queryset = queryset.filter(is_enabled=is_enabled.lower() == "true")

        # Search by title if provided
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(title__icontains=search)

        return queryset.order_by("-created_at")
