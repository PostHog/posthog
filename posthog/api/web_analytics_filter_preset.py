from typing import Any, Optional

from django.db.models import Q, QuerySet
from django.utils.timezone import now

from django_filters.rest_framework import DjangoFilterBackend
from loginas.utils import is_impersonated_session
from rest_framework import serializers, viewsets

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import User
from posthog.models.activity_logging.activity_log import Change, Detail, changes_between, log_activity
from posthog.models.utils import UUIDT
from posthog.models.web_analytics_filter_preset import WebAnalyticsFilterPreset


def log_preset_activity(
    activity: str,
    preset: WebAnalyticsFilterPreset,
    preset_id: int,
    preset_short_id: str,
    organization_id: UUIDT,
    team_id: int,
    user: User,
    was_impersonated: bool,
    changes: Optional[list[Change]] = None,
) -> None:
    if preset.name:
        log_activity(
            organization_id=organization_id,
            team_id=team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=preset_id,
            scope="WebAnalyticsFilterPreset",
            activity=activity,
            detail=Detail(name=preset.name, changes=changes, short_id=preset_short_id),
        )


class WebAnalyticsFilterPresetSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebAnalyticsFilterPreset
        fields = [
            "id",
            "short_id",
            "name",
            "description",
            "pinned",
            "created_at",
            "created_by",
            "deleted",
            "filters",
            "last_modified_at",
            "last_modified_by",
        ]
        read_only_fields = [
            "id",
            "short_id",
            "team",
            "created_at",
            "created_by",
            "last_modified_at",
            "last_modified_by",
        ]

    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> WebAnalyticsFilterPreset:
        request = self.context["request"]
        team = self.context["get_team"]()

        created_by = validated_data.pop("created_by", request.user)

        preset = WebAnalyticsFilterPreset.objects.create(
            team=team,
            created_by=created_by,
            last_modified_by=request.user,
            **validated_data,
        )

        log_preset_activity(
            activity="created",
            preset=preset,
            preset_id=preset.id,
            preset_short_id=preset.short_id,
            organization_id=request.user.current_organization_id,
            team_id=team.id,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
        )

        return preset

    def update(
        self, instance: WebAnalyticsFilterPreset, validated_data: dict, **kwargs: Any
    ) -> WebAnalyticsFilterPreset:
        try:
            before_update = WebAnalyticsFilterPreset.objects.get(pk=instance.id)
        except WebAnalyticsFilterPreset.DoesNotExist:
            before_update = None

        if validated_data.keys() & WebAnalyticsFilterPreset.LAST_MODIFIED_FIELDS:
            instance.last_modified_at = now()
            instance.last_modified_by = self.context["request"].user

        updated_preset = super().update(instance, validated_data)
        changes = changes_between("WebAnalyticsFilterPreset", previous=before_update, current=updated_preset)

        log_preset_activity(
            activity="updated",
            preset=updated_preset,
            preset_id=updated_preset.id,
            preset_short_id=updated_preset.short_id,
            organization_id=self.context["request"].user.current_organization_id,
            team_id=self.context["team_id"],
            user=self.context["request"].user,
            was_impersonated=is_impersonated_session(self.context["request"]),
            changes=changes,
        )

        return updated_preset


class WebAnalyticsFilterPresetViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = WebAnalyticsFilterPreset.objects.all()
    serializer_class = WebAnalyticsFilterPresetSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["short_id", "created_by"]
    lookup_field = "short_id"

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        if not self.action.endswith("update"):
            queryset = queryset.filter(deleted=False)

        queryset = queryset.select_related("created_by", "last_modified_by", "team")

        if self.action == "list":
            queryset = self._filter_request(self.request, queryset)

        order = self.request.GET.get("order", None)
        if order:
            queryset = queryset.order_by(order)
        else:
            queryset = queryset.order_by("-last_modified_at")

        return queryset

    def _filter_request(self, request: Any, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            request_value = filters[key]
            if key == "user":
                queryset = queryset.filter(created_by=request.user)
            elif key == "created_by":
                queryset = queryset.filter(created_by=request_value)
            elif key == "pinned":
                queryset = queryset.filter(pinned=True)
            elif key == "search":
                queryset = queryset.filter(
                    Q(name__icontains=request.GET["search"]) | Q(description__icontains=request.GET["search"])
                )

        return queryset
