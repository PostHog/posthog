from typing import Any, Dict
from django.db import transaction
from django.db.models import QuerySet

from rest_framework import exceptions, serializers, viewsets, pagination
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.comment import Comment


class CommentSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Comment
        exclude = []
        read_only_fields = ["id", "created_by", "version"]

    def validate(self, data):
        request = self.context["request"]

        if self.instance:
            if self.instance.created_by != request.user:
                raise exceptions.PermissionDenied("You can only modify your own comments")
        # TODO: Ensure created_by is set
        # And only allow updates to own comment

        data["created_by"] = request.user

        return data

    def update(self, instance: Comment, validated_data: Dict, **kwargs) -> Comment:
        request = self.context["request"]

        with transaction.atomic():
            # select_for_update locks the database row so we ensure version updates are atomic
            locked_instance = Comment.objects.select_for_update().get(pk=instance.pk)

            if locked_instance.created_by != request.user:
                raise

            if validated_data.keys():
                if validated_data.get("content"):
                    validated_data["version"] = locked_instance.version + 1

                updated_instance = super().update(locked_instance, validated_data)

        return updated_instance


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
