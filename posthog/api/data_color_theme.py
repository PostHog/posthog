from rest_framework import serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response
from django.db.models import Q

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import SharingAccessTokenAuthentication
from posthog.models import DataColorTheme


class GlobalThemePermission(BasePermission):
    message = "Only staff users can edit global themes."

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True
        elif view.team == obj.team:
            return True
        return request.user.is_staff


class PublicDataColorThemeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataColorTheme
        fields = ["id", "name", "colors", "is_global"]
        read_only_fields = ["id", "name", "colors", "is_global"]


class DataColorThemeSerializer(PublicDataColorThemeSerializer):
    is_global = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = DataColorTheme
        fields = ["id", "name", "colors", "is_global", "created_at", "created_by"]
        read_only_fields = [
            "id",
            "is_global",
            "created_at",
            "created_by",
        ]

    def create(self, validated_data: dict, *args, **kwargs) -> DataColorTheme:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data, *args, **kwargs)

    def get_is_global(self, obj):
        return obj.team_id is None


class DataColorThemeViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = DataColorTheme.objects.all().order_by("-created_at")
    serializer_class = DataColorThemeSerializer
    permission_classes = [GlobalThemePermission]
    sharing_enabled_actions = ["retrieve", "list"]

    # override the team scope queryset to also include global themes
    def dangerously_get_queryset(self):
        query_condition = Q(team_id=self.team_id) | Q(team_id=None)

        return DataColorTheme.objects.filter(query_condition)

    def get_serializer_class(self):
        if isinstance(self.request.successful_authenticator, SharingAccessTokenAuthentication):
            return PublicDataColorThemeSerializer
        return DataColorThemeSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
