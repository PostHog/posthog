from datetime import datetime
from typing import Any, cast

import emoji
from django.db.models import Q, QuerySet
from django.db.models.signals import post_save
from django.dispatch import receiver
from loginas.utils import is_impersonated_session
from rest_framework import filters, serializers, viewsets, pagination

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import Annotation
from posthog.models.activity_logging.activity_log import Detail, Change, log_activity
from posthog.models.utils import UUIDT


class AnnotationSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Annotation
        fields = [
            "id",
            "content",
            "date_marker",
            "creation_type",
            "dashboard_item",
            "dashboard_id",
            "dashboard_name",
            "insight_short_id",
            "insight_name",
            "insight_derived_name",
            "created_by",
            "created_at",
            "updated_at",
            "deleted",
            "scope",
            "recording_id",
            "is_emoji",
            "tagged_users",
        ]
        read_only_fields = [
            "id",
            "insight_short_id",
            "insight_name",
            "insight_derived_name",
            "dashboard_name",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def update(self, instance: Annotation, validated_data: dict[str, Any]) -> Annotation:
        instance.team_id = self.context["team_id"]

        # Store before state for activity logging
        tagged_users_before = set(instance.tagged_users or [])

        # Perform the update
        instance = super().update(instance, validated_data)

        # Check if tagged_users changed and log activity
        tagged_users_after = set(instance.tagged_users or [])
        newly_tagged_users = tagged_users_after - tagged_users_before

        if newly_tagged_users:
            self._log_user_tagging_activity(instance, list(newly_tagged_users))

        return instance

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        is_emoji = attrs.get("is_emoji", False)
        content = attrs.get("content", "")

        if is_emoji and content:
            # Check if content is an emoji
            if not emoji.is_emoji(content):
                raise serializers.ValidationError("When is_emoji is True, content must be a single emoji")
        elif is_emoji and not content:
            raise serializers.ValidationError("When is_emoji is True, content cannot be empty")

        if attrs.get("tagged_users", []):
            """
            Each tagged user should be in the content
            If they're not we can simply remove them,
            it doesn't need to be rejected
            """
            validated_tagged_users = []
            for tagged_user in attrs.get("tagged_users", []):
                if tagged_user in content:
                    validated_tagged_users.append(tagged_user)

            attrs["tagged_users"] = validated_tagged_users

        return attrs

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> Annotation:
        request = self.context["request"]
        team = self.context["get_team"]()
        annotation = Annotation.objects.create(
            organization_id=team.organization_id,
            team_id=team.id,
            created_by=request.user,
            dashboard_id=request.data.get("dashboard_id", None),
            **validated_data,
        )

        # Log activity for newly tagged users
        tagged_users = annotation.tagged_users or []
        if tagged_users:
            self._log_user_tagging_activity(annotation, tagged_users)

        return annotation

    def _log_user_tagging_activity(self, annotation: Annotation, tagged_users: list[str]) -> None:
        """Log activity when users are tagged in annotations."""
        request = self.context["request"]

        for tagged_user in tagged_users:
            log_activity(
                organization_id=cast(UUIDT, annotation.organization_id),
                team_id=annotation.team_id,
                user=request.user,
                was_impersonated=is_impersonated_session(request),
                scope="Replay" if annotation.scope == Annotation.Scope.RECORDING else annotation.scope,
                item_id=annotation.id,
                activity="tagged_user",
                detail=Detail(
                    name=tagged_user,
                    changes=[
                        Change(
                            type="Replay" if annotation.scope == Annotation.Scope.RECORDING else annotation.scope,
                            action="tagged_user",
                            after={
                                "tagged_user": tagged_user,
                                "annotation_scope": annotation.scope,
                                "annotation_recording_id": annotation.recording_id,
                                "annotation_insight_id": annotation.insight_short_id,
                                "annotation_dashboard_id": annotation.dashboard_id,
                            },
                        )
                    ],
                ),
            )


class AnnotationsLimitOffsetPagination(pagination.LimitOffsetPagination):
    default_limit = 1000


class AnnotationsViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
    """

    scope_object = "annotation"
    queryset = Annotation.objects.select_related("dashboard_item").select_related("created_by")
    serializer_class = AnnotationSerializer
    filter_backends = [filters.SearchFilter]
    pagination_class = AnnotationsLimitOffsetPagination
    search_fields = ["content"]

    def safely_get_queryset(self, queryset) -> QuerySet:
        if self.action == "list":
            queryset = queryset.order_by("-date_marker")
        if self.action != "partial_update":
            # We never want deleted items to be included in the queryset… except when we want to restore an annotation
            # That's because annotations are restored with a PATCH request setting `deleted` to `False`
            queryset = queryset.filter(deleted=False)

        scope = self.request.query_params.get("scope")
        if scope:
            # let's allow the more recently used "insight" scope to be used as "dashboard_item"
            scope = "dashboard_item" if scope == "insight" else scope
            if scope not in [s.value for s in Annotation.Scope]:
                raise serializers.ValidationError(f"Invalid scope: {scope}")

            queryset = queryset.filter(scope=scope)

        # Add date range filtering
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")

        date_from_parsed = None
        date_to_parsed = None

        if date_from:
            try:
                date_from_parsed = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
                queryset = queryset.filter(date_marker__gte=date_from_parsed)
            except ValueError:
                raise serializers.ValidationError("Invalid date range: date_from must be a valid ISO 8601 date")

        if date_to:
            try:
                date_to_parsed = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
                queryset = queryset.filter(date_marker__lte=date_to_parsed)
            except ValueError:
                raise serializers.ValidationError("Invalid date range: date_to must be a valid ISO 8601 date")

        if date_from_parsed and date_to_parsed and date_from_parsed > date_to_parsed:
            raise serializers.ValidationError("Invalid date range: date_from must be before date_to")

        # Add is_emoji filtering
        is_emoji = self.request.query_params.get("is_emoji")
        if is_emoji is not None:
            # Convert string to boolean (true, 1, yes -> True; false, 0, no -> False)
            is_emoji_bool = is_emoji.lower() in ("true", "1", "yes")
            queryset = queryset.filter(is_emoji=is_emoji_bool)

        return queryset

    def _filter_queryset_by_parents_lookups(self, queryset):
        team = self.team
        return queryset.filter(
            Q(scope=Annotation.Scope.ORGANIZATION, organization_id=team.organization_id) | Q(team=team)
        )


@receiver(post_save, sender=Annotation, dispatch_uid="hook-annotation-created")
def annotation_created(sender, instance, created, raw, using, **kwargs):
    if instance.created_by:
        event_name: str = "annotation created" if created else "annotation updated"
        report_user_action(instance.created_by, event_name, instance.get_analytics_metadata())
