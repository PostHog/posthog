from typing import Any, Dict

import posthoganalytics
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.mixins import AnalyticsDestroyModelMixin
from posthog.models import SessionsFilter
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class SessionsFilterSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = SessionsFilter
        fields = ["id", "name", "created_by", "created_at", "updated_at", "filters"]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> SessionsFilter:
        request = self.context["request"]
        instance = SessionsFilter.objects.create(
            team_id=self.context["team_id"], created_by=request.user, **validated_data,
        )
        posthoganalytics.capture(instance.created_by.distinct_id, "sessions filter created")
        return instance


class SessionsFilterViewSet(StructuredViewSetMixin, AnalyticsDestroyModelMixin, viewsets.ModelViewSet):
    queryset = SessionsFilter.objects.all().order_by("name")
    serializer_class = SessionsFilterSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]


class LegacySessionsFilterViewSet(SessionsFilterViewSet):
    legacy_team_compatibility = True
