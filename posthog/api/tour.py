from django.db.utils import IntegrityError
from rest_framework import mixins, request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.mixins import AnalyticsDestroyModelMixin
from posthog.models.cohort import CohortPeople
from posthog.models.person import PersonDistinctId
from posthog.models.tour import Tour, TourPerson
from posthog.permissions import ProjectMembershipNecessaryPermissions


class TourSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tour
        fields = [
            "id",
            "cohort",
            "team",
            "name",
            "trigger_url_regex",
            "delay_ms",
            "is_active",
            "steps",
        ]


class TourPersonSerializer(serializers.ModelSerializer):
    distinct_id = serializers.CharField(required=True)

    class Meta:
        model = TourPerson
        fields = [
            "tour",
            "is_started",
            "distinct_id",
        ]

    def create(self, validated_data):
        distinct_id = validated_data.pop("distinct_id")
        person = PersonDistinctId.objects.get(distinct_id=distinct_id, team_id=self.context["team_id"]).person
        instance = TourPerson.objects.create(
            person=person, tour=validated_data.pop("tour"), is_started=validated_data.pop("is_started")
        )
        return instance


class TourViewSet(StructuredViewSetMixin, AnalyticsDestroyModelMixin, viewsets.ModelViewSet):
    queryset = Tour.objects.all()
    serializer_class = TourSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions]

    # TODO: Account for users who already saw the tour
    @action(methods=["GET"], detail=False, permission_classes=[AllowAny])
    def for_user(self, request: request.Request, **kwargs):
        distinct_id = request.GET.get("distinct_id", None)
        if not distinct_id:
            raise serializers.ValidationError("Please provide a distinct_id to continue.")
        try:
            person = PersonDistinctId.objects.get(team=self.team_id, distinct_id=distinct_id).person
        except PersonDistinctId.DoesNotExist:
            raise serializers.ValidationError("Distinct ID is not found.")
        cohort_ids = CohortPeople.objects.filter(person=person).values_list("cohort")
        completed_tour_ids = TourPerson.objects.filter(person=person).values_list("tour")
        queryset = (
            super().get_queryset().filter(cohort__id__in=cohort_ids, is_active=True).exclude(id__in=completed_tour_ids)
        )
        serializer = self.serializer_class(queryset, many=True)
        return Response(serializer.data)


class TourPersonViewset(StructuredViewSetMixin, viewsets.GenericViewSet):
    serializer_class = TourPersonSerializer
    permission_classes = [
        AllowAny,
    ]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"success": True})
