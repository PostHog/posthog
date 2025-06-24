from rest_framework import serializers, viewsets, status
from rest_framework.response import Response

from posthog.api.shared import UserBasicSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.user_group import UserGroup, UserGroupMembership


class UserGroupSerializer(serializers.ModelSerializer):
    members = UserBasicSerializer(many=True, read_only=True)

    class Meta:
        model = UserGroup
        fields = ["id", "name", "members"]

    def create(self, validated_data: dict, *args, **kwargs) -> UserGroup:
        return UserGroup.objects.create(
            team=self.context["get_team"](),
            **validated_data,
        )


class UserGroupViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = UserGroup.objects.all()
    serializer_class = UserGroupSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team)

    @action(methods=["POST"], detail=True)
    def add(self, request, **kwargs):
        group = self.get_object()
        UserGroupMembership.objects.get_or_create(group=group, user_id=request.data["userId"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["POST"], detail=True)
    def remove(self, request, **kwargs):
        group = self.get_object()
        UserGroupMembership.objects.filter(group=group, user_id=request.data["userId"]).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
