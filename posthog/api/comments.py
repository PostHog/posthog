from typing import Any, cast
from django.db import transaction
from django.db.models import QuerySet

from rest_framework import exceptions, serializers, viewsets, pagination
from posthog.api.utils import action
from rest_framework.request import Request
from rest_framework.response import Response
from loginas.utils import is_impersonated_session

from posthog.api.forbid_destroy_model import ForbidDestroyModel

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import ClassicBehaviorBooleanFieldSerializer
from posthog.models.comment import Comment
from posthog.models import User
from posthog.models.activity_logging.activity_log import Detail, Change, log_activity
from posthog.models.utils import UUIDT


class CommentSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    scope = serializers.CharField(required=True)
    deleted = ClassicBehaviorBooleanFieldSerializer()

    class Meta:
        model = Comment
        exclude = ["team"]
        read_only_fields = ["id", "created_by", "version"]

    def validate(self, data):
        request = self.context["request"]
        instance = cast(Comment, self.instance)

        if instance:
            if instance.created_by != request.user:
                raise exceptions.PermissionDenied("You can only modify your own comments")

        data["created_by"] = request.user

        if data.get("tagged_users", []):
            data["tagged_users"] = self._check_tagged_users_exist(data)

        return data

    @staticmethod
    def _check_tagged_users_exist(attrs: dict[str, Any]) -> list[str]:
        """
        Each tagged user is the UUID of a user tagged in the content
        we don't validate they're really in the content,
        but they should be a valid user
        """
        # TODO: and visible to the user creating the content
        validated_tagged_users = []
        for tagged_user in attrs.get("tagged_users", []):
            if User.objects.filter(uuid=tagged_user).exists():
                validated_tagged_users.append(tagged_user)

        return validated_tagged_users

    def _log_user_tagging_activity(self, comment: Comment, tagged_users: list[str]) -> None:
        """Log activity when users are tagged in comments."""
        request = self.context["request"]

        for tagged_user in tagged_users:
            # Comments can be on various things, but the activity scope is always "Comment"
            # unless it's a reply, then the scope is the original comment
            scope = "Comment" if comment.source_comment_id else comment.scope
            item_id = cast(str, comment.source_comment_id) or comment.item_id

            log_activity(
                organization_id=cast(UUIDT, comment.team.organization_id),
                team_id=comment.team_id,
                user=request.user,
                was_impersonated=is_impersonated_session(request),
                scope=scope,
                item_id=item_id,
                activity="tagged_user",
                detail=Detail(
                    name=tagged_user,
                    changes=[
                        Change(
                            type="Comment",
                            action="tagged_user",
                            after={
                                "tagged_user": tagged_user,
                                "comment_scope": comment.scope,
                                "comment_item_id": comment.item_id,
                                "comment_content": comment.content,
                                "comment_source_comment_id": str(comment.source_comment_id)
                                if comment.source_comment_id
                                else None,
                            },
                        )
                    ],
                ),
            )

    def create(self, validated_data: Any) -> Any:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["tagged_users"] = self._check_tagged_users_exist(validated_data)

        comment = super().create(validated_data)

        # Log activity for newly tagged users
        tagged_users = comment.tagged_users or []
        if tagged_users:
            self._log_user_tagging_activity(comment, tagged_users)

        return comment

    def update(self, instance: Comment, validated_data: dict, **kwargs) -> Comment:
        request = self.context["request"]

        with transaction.atomic():
            # select_for_update locks the database row so we ensure version updates are atomic
            locked_instance = Comment.objects.select_for_update().get(pk=instance.pk)

            if locked_instance.created_by != request.user:
                raise exceptions.PermissionDenied("You can only modify your own comments")

            # Store before state for activity logging
            tagged_users_before = set(locked_instance.tagged_users or [])

            if validated_data.keys():
                if validated_data.get("content"):
                    validated_data["version"] = locked_instance.version + 1

                updated_instance = super().update(locked_instance, validated_data)

                # Check if tagged_users changed and log activity
                tagged_users_after = set(updated_instance.tagged_users or [])
                newly_tagged_users = tagged_users_after - tagged_users_before

                if newly_tagged_users:
                    self._log_user_tagging_activity(updated_instance, list(newly_tagged_users))

        return updated_instance


class CommentPagination(pagination.CursorPagination):
    ordering = "-created_at"
    page_size = 100


class CommentViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    pagination_class = CommentPagination
    scope_object = "INTERNAL"

    def safely_get_queryset(self, queryset) -> QuerySet:
        params = self.request.GET.dict()

        if params.get("user"):
            queryset = queryset.filter(user=params.get("user"))

        if self.action != "partial_update" and params.get("deleted", "false") == "false":
            queryset = queryset.filter(deleted=False)

        if params.get("scope"):
            queryset = queryset.filter(scope=params.get("scope"))

        if params.get("item_id"):
            queryset = queryset.filter(item_id=params.get("item_id"))

        source_comment = params.get("source_comment")
        if self.action == "thread":
            # Filter based on the source_comment
            source_comment = self.kwargs.get("pk")

        if source_comment:
            # NOTE: Should we also return the source_comment ?
            queryset = queryset.filter(source_comment_id=source_comment)

        return queryset

    @action(methods=["GET"], detail=True)
    def thread(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.list(request, *args, **kwargs)

    @action(methods=["GET"], detail=False)
    def count(self, request: Request, **kwargs) -> Response:
        queryset = self.get_queryset()
        count = queryset.count()

        return Response({"count": count})
