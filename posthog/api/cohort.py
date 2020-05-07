from rest_framework import request, response, serializers, viewsets
from posthog.models import Cohort
from typing import Dict, Any
from posthog.api.user import UserSerializer
from posthog.tasks.calculate_cohort import calculate_cohort
from django.db.models import QuerySet

class CohortSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(required=False, read_only=True)

    class Meta:
        model = Cohort
        fields = ['id', 'name', 'groups', 'deleted', 'is_calculating', 'created_by', 'created_at', 'last_calculation']

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:
        request = self.context['request']
        validated_data['created_by'] = request.user
        cohort = Cohort.objects.create(team=request.user.team_set.get(), **validated_data)
        calculate_cohort.delay(cohort_id=cohort.pk)
        return cohort

    def update(self, cohort: Cohort, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:  # type: ignore
        cohort.name = validated_data.get('name', cohort.name)
        cohort.groups = validated_data.get('groups', cohort.groups)
        cohort.deleted = validated_data.get('deleted', cohort.deleted)
        cohort.save()
        calculate_cohort.delay(cohort_id=cohort.pk)
        return cohort


class CohortViewSet(viewsets.ModelViewSet):
    queryset = Cohort.objects.all()
    serializer_class = CohortSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == 'list':  # type: ignore
            queryset = queryset.filter(deleted=False)
        return queryset\
            .filter(team=self.request.user.team_set.get())\
            .order_by('id')
