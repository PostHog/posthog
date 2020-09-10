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


import posthoganalytics
from django.contrib.auth import login, password_validation
from django.db import transaction
from rest_framework import generics, permissions, serializers

from posthog.api.user import UserSerializer
from posthog.models import Team, User
from posthog.models.user import EE_MISSING, MULTI_TENANCY_MISSING


class TeamSignupSerializer(serializers.Serializer):
    first_name: serializers.Field = serializers.CharField(max_length=128)
    email: serializers.Field = serializers.EmailField()
    password: serializers.Field = serializers.CharField()
    company_name: serializers.Field = serializers.CharField(
        max_length=128, required=False, allow_blank=True,
    )
    email_opt_in: serializers.Field = serializers.BooleanField(default=True)

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value

    def create(self, validated_data):
        company_name = validated_data.pop("company_name", "")
        is_first_user: bool = not User.objects.exists()
        realm: str = "cloud" if not MULTI_TENANCY_MISSING else "hosted"

        if self.context["request"].user.is_authenticated:
            raise serializers.ValidationError("Authenticated users may not create additional teams.")

        if not is_first_user and MULTI_TENANCY_MISSING:
            raise serializers.ValidationError("This instance does not support multiple teams.")

        with transaction.atomic():
            user = User.objects.create_user(**validated_data)
            self._team = Team.objects.create_with_data(users=[user], name=company_name)

        login(
            self.context["request"], user, backend="django.contrib.auth.backends.ModelBackend",
        )

        posthoganalytics.capture(
            user.distinct_id, "user signed up", properties={"is_first_user": is_first_user, "is_team_first_user": True},
        )

        posthoganalytics.identify(
            user.distinct_id, properties={"email": user.email, "realm": realm, "ee_available": not EE_MISSING},
        )

        return user

    def to_representation(self, instance):
        serializer = UserSerializer(instance=instance)
        return serializer.data


class TeamSignupViewset(generics.CreateAPIView):
    serializer_class = TeamSignupSerializer
    permission_classes = (permissions.AllowAny,)
