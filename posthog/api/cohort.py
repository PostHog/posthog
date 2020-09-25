from typing import Any, Dict, Optional

from django.db.models import Count, QuerySet
from rest_framework import request, response, serializers, viewsets

from posthog.api.user import UserSerializer
from posthog.models import Cohort
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
            "count",
        ]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["is_calculating"] = True
        cohort = Cohort.objects.create(team=request.user.team, **validated_data)
        calculate_cohort.delay(cohort_id=cohort.pk)
        return cohort

    def update(self, cohort: Cohort, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:  # type: ignore
        cohort.name = validated_data.get("name", cohort.name)
        cohort.groups = validated_data.get("groups", cohort.groups)
        cohort.deleted = validated_data.get("deleted", cohort.deleted)
        cohort.is_calculating = True
        cohort.save()
        calculate_cohort.delay(cohort_id=cohort.pk)
        return cohort

    def get_count(self, action: Cohort) -> Optional[int]:
        if hasattr(action, "count"):
            return action.count  # type: ignore
        return None


class CohortViewSet(viewsets.ModelViewSet):
    queryset = Cohort.objects.all()
    serializer_class = CohortSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":  # type: ignore
            queryset = queryset.filter(deleted=False)

        queryset = queryset.annotate(count=Count("people"))
        return queryset.filter(team=self.request.user.team).select_related("created_by").order_by("id")
