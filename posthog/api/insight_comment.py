from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import InsightComment


class InsightCommentSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = InsightComment
        fields = [
            "id",
            "insight",
            "comment",
            "created_at",
            "created_by",
        ]


class InsightCommentsViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = InsightComment.objects.all()
    serializer_class = InsightCommentSerializer
    permission_classes = [IsAuthenticated]
