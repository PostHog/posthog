import json
from typing import Any, Dict, Union

import posthoganalytics
from django.conf import settings
from django.contrib.auth import login, password_validation
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Func, OuterRef, Prefetch, Q, QuerySet, Subquery
from django.shortcuts import get_object_or_404
from rest_framework import (
    generics,
    mixins,
    permissions,
    request,
    response,
    serializers,
    status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.serializers import raise_errors_on_nested_writes
from rest_framework.settings import api_settings
from rest_framework.utils import model_meta
from rest_framework_csv import renderers as csvrenderers  # type: ignore

from posthog.api.user import UserSerializer
from posthog.models import Cohort, Event, Filter, Person, PersonDistinctId, Team, User
from posthog.models.user import MULTI_TENANCY_MISSING
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

    def create(self, validated_data: Dict[str, Any]) -> Team:
        raise_errors_on_nested_writes("create", self, validated_data)
        request = self.context["request"]
        with transaction.atomic():
            team = Team.objects.create(**validated_data, organization=request.user.organization)
            request.user.current_team = team
            request.user.save()
        return team


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


class TeamSignupSerializer(serializers.Serializer):
    first_name: serializers.Field = serializers.CharField(max_length=128)
    email: serializers.Field = serializers.EmailField()
    password: serializers.Field = serializers.CharField()
    company_name: serializers.Field = serializers.CharField(max_length=128, required=False, allow_blank=True)
    email_opt_in: serializers.Field = serializers.BooleanField(default=True)

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value

    def create(self, validated_data):
        is_first_user: bool = not User.objects.exists()
        realm: str = "cloud" if not MULTI_TENANCY_MISSING else "hosted"

        if self.context["request"].user.is_authenticated:
            raise serializers.ValidationError("Authenticated users may not create additional teams.")

        if not is_first_user and MULTI_TENANCY_MISSING:
            raise serializers.ValidationError("This instance does not support multiple teams.")

        company_name = validated_data.pop("company_name", validated_data["first_name"])
        self._organization, self._team, self._user = User.objects.bootstrap(company_name=company_name, **validated_data)
        user = self._user
        login(
            self.context["request"], user, backend="django.contrib.auth.backends.ModelBackend",
        )

        posthoganalytics.capture(
            user.distinct_id,
            "user signed up",
            properties={"is_first_user": is_first_user, "is_organization_first_user": True},
        )

        posthoganalytics.identify(
            user.distinct_id, properties={"email": user.email, "realm": realm, "ee_available": settings.EE_AVAILABLE},
        )

        return user

    def to_representation(self, instance):
        serializer = UserSerializer(instance=instance)
        return serializer.data


class TeamSignupViewset(generics.CreateAPIView):
    serializer_class = TeamSignupSerializer
    permission_classes = (permissions.AllowAny,)
