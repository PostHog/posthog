import json
from typing import Union

from django.core.cache import cache
from django.db.models import Count, Func, OuterRef, Prefetch, Q, QuerySet, Subquery
from django.shortcuts import get_object_or_404
from rest_framework import mixins, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers  # type: ignore

from posthog.models import Cohort, Event, Filter, Person, PersonDistinctId, Team
from posthog.utils import convert_property_value


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = (
            "id",
            "organization",
            "api_token",
            "app_urls",
            "name",
            "slack_incoming_webhook",
            "event_names",
            "event_properties",
            "event_properties_numerical",
            "created_at",
            "updated_at",
            "anonymize_ips",
            "completed_snippet_onboarding",
            "ingested_event",
            "uuid",
            "opt_out_capture",
        )
        read_only_fields = (
            "id",
            "uuid",
            "organization",
            "api_token",
            "event_names",
            "event_properties",
            "event_properties_numerical",
            "created_at",
            "updated_at",
            "ingested_event",
            "opt_out_capture",
        )


class TeamViewSet(viewsets.ModelViewSet):
    queryset = Team.objects.all()
    serializer_class = TeamSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(organization__in=self.request.user.organizations)
        return self._filter_request(self.request, queryset)  # type: ignore

    def retrieve(self, request, pk=None):
        queryset = self.get_queryset()
        if pk == "@current":
            pk = self.request.user.current_team_id
        team = get_object_or_404(queryset, pk=pk)
        serializer = TeamSerializer(team)
        return response.Response(serializer.data)
