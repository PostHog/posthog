from django.db.models import QuerySet
from rest_framework import request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.mixins import AnalyticsDestroyModelMixin
from posthog.models.cohort import CohortPeople
from posthog.models.person import PersonDistinctId
from posthog.models.tour import Tour
from posthog.permissions import ProjectMembershipNecessaryPermissions


class TourSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tour
        fields = [
            "uuid",
            "cohort",
            "team",
            "name",
            "trigger_url_regex",
            "delay_ms",
            "is_active",
            "steps",
        ]


class TourViewSet(StructuredViewSetMixin, AnalyticsDestroyModelMixin, viewsets.ModelViewSet):
    queryset = Tour.objects.all()
    serializer_class = TourSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions]

    # TODO: Account for users who already saw the tour
    @action(methods=["GET"], detail=False, permission_classes=[AllowAny])
    def for_user(self, request: request.Request):
        distinct_id = request.GET.get("distinct_id", None)
        if not distinct_id:
            raise serializers.ValidationError("Please provide a distinct_id to continue.")
        try:
            person = PersonDistinctId.objects.get(team=self.team_id, distinct_id=distinct_id).person
        except PersonDistinctId.DoesNotExist:
            raise serializers.ValidationError("Distinct ID is not found.")
        cohort_ids = CohortPeople.objects.filter(person=person).values_list("cohort")
        queryset = super().get_queryset().filter(cohort__id__in=cohort_ids, is_active=True)
        serializer = self.serializer_class(queryset, many=True)
        return Response(serializer.data)
