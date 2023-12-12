from typing import Any
from django.db.models import QuerySet

from rest_framework import serializers, viewsets, pagination
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel

from posthog.api.routing import StructuredViewSetMixin
from posthog.models.comment import Comment


class CommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        exclude = []
        read_only_fields = ["id", "created_by"]


class CommentPagination(pagination.CursorPagination):
    ordering = "-created_at"
    page_size = 100


class CommentViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    pagination_class = CommentPagination

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        params = self.request.GET.dict()

        if params.get("user"):
            queryset = queryset.filter(user=params.get("user"))

        if params.get("scope"):
            queryset = queryset.filter(scope=params.get("scope"))

        if params.get("item_id"):
            queryset = queryset.filter(item_id=params.get("item_id"))

        if self.action == "thread":
            # Filter based on the source_comment_id
            object_id = self.kwargs.get("pk")
            queryset = queryset.filter(source_comment_id=object_id)

        return queryset

    @action(methods=["GET"], detail=True)
    def thread(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.list(request, *args, **kwargs)
