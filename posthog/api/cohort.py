from typing import Any, Dict, Optional

import posthoganalytics
from django.db.models import Count, QuerySet
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.user import UserSerializer
from posthog.models import Cohort
from posthog.permissions import ProjectMembershipNecessaryPermissions
from posthog.tasks.calculate_cohort import calculate_cohort


class CohortSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(required=False, read_only=True)
    count = serializers.SerializerMethodField()

    class Meta:
        model = Cohort
        fields = [
            "id",
            "name",
            "groups",
            "deleted",
            "is_calculating",
            "created_by",
            "created_at",
            "last_calculation",
            "errors_calculating",
            "count",
        ]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["is_calculating"] = True
        cohort = Cohort.objects.create(team_id=self.context["team_id"], **validated_data)
        posthoganalytics.capture(request.user.distinct_id, "cohort created", cohort.get_analytics_metadata())
        calculate_cohort.delay(cohort_id=cohort.pk)
        return cohort

    def update(self, cohort: Cohort, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:  # type: ignore
        request = self.context["request"]
        cohort.name = validated_data.get("name", cohort.name)
        cohort.groups = validated_data.get("groups", cohort.groups)
        cohort.deleted = validated_data.get("deleted", cohort.deleted)
        cohort.is_calculating = True
        cohort.save()
        posthoganalytics.capture(
            request.user.distinct_id,
            "cohort updated",
            {**cohort.get_analytics_metadata(), "updated_by_creator": request.user == cohort.created_by},
        )
        calculate_cohort.delay(cohort_id=cohort.pk)
        return cohort

    def get_count(self, action: Cohort) -> Optional[int]:
        if hasattr(action, "count"):
            return action.count  # type: ignore
        return None


class CohortViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    legacy_team_compatibility = True  # to be moved to a separate Legacy*ViewSet Class

    queryset = Cohort.objects.all()
    serializer_class = CohortSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = queryset.filter(deleted=False)

        queryset = queryset.annotate(count=Count("people"))
        return queryset.select_related("created_by").order_by("id")
