import json
from typing import Union

from django.core.cache import cache
from django.db.models import Count, Func, OuterRef, Prefetch, Q, QuerySet, Subquery
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers  # type: ignore

from posthog.models import Cohort, Event, Filter, Person, PersonDistinctId, Team
from posthog.utils import convert_property_value


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = [
            "id",
            "name",
            "distinct_ids",
            "properties",
            "created_at",
        ]

    def get_name(self, person: Person) -> str:
        if person.properties.get("email"):
            return person.properties["email"]
        if len(person.distinct_ids) > 0:
            return person.distinct_ids[-1]
        return person.pk


class TeamViewSet(mixins.DestroyModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Team.objects.all()
    serializer_class = TeamSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        team = self.request.user.organization.team
        queryset = queryset.filter(team=team)
        return self._filter_request(self.request, queryset, team)
