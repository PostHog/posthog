from rest_framework import exceptions, request, response, serializers, viewsets
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin

from ee.clickhouse.client import sync_execute
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.group_type import GroupTypeMapping


class GroupSerializer(serializers.Serializer):
    id = serializers.CharField()
    type_id = serializers.IntegerField(max_value=5)
    created_at = serializers.DateTimeField()
    properties = serializers.JSONField()


class ClickhouseGroupsView(StructuredViewSetMixin, viewsets.ViewSet):
    serializer_class = GroupSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = sync_execute(
            "SELECT id, type_id, created_at, properties FROM groups WHERE team_id = %(team_id)s AND id = %(group_id)s",
            {"team_id": self.team_id, "group_id": self.kwargs["id"]},
        )
        if not instance:
            raise exceptions.NotFound(detail="Group not found.")
        serializer = self.serializer_class(instance[0])
        return response.Response(serializer.data)

    def list(self, request, *args, **kwargs):
        instances = sync_execute(
            "SELECT id, type_id, created_at, team_id, properties FROM groups WHERE team_id = %(team_id)s",
            {"team_id": self.team_id},
        )
        serializer = self.serializer_class(instances, many=True)
        return response.Response(serializer.data)


class GroupTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupTypeMapping
        fields = ["type_key", "type_id"]


class ClickhouseGroupTypesView(StructuredViewSetMixin, ListModelMixin, RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = GroupTypeSerializer
    queryset = GroupTypeMapping.objects.all()
