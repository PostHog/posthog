import json

from rest_framework import exceptions, request, response, serializers, viewsets
from rest_framework.decorators import action
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
            "SELECT id, type_id, created_at, properties FROM groups WHERE team_id = %(team_id)s AND type_id = %(type_id)s AND id = %(id)s",
            {"team_id": self.team_id, "id": self.kwargs["id"], "type_id": self.kwargs["type_id"]},
        )
        if not instance:
            raise exceptions.NotFound(detail="Group not found.")
        serializer = self.serializer_class(instance[0])
        return response.Response(serializer.data)

    def list(self, request, *args, **kwargs):
        group_type_mapping = GroupTypeMapping.objects.get(
            team_id=self.team_id, type_key=self.kwargs["parent_lookup_type_key"]
        )
        instances = (
            {"id": row[0], "type_id": row[1], "created_at": row[2], "team_id": row[3], "properties": json.loads(row[4])}
            for row in sync_execute(
                """
                SELECT id, type_id, created_at, team_id, properties FROM groups
                WHERE team_id = %(team_id)s AND type_id = %(type_id)s
            """,
                {"team_id": self.team_id, "type_id": group_type_mapping.type_id},
            )
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
    pagination_class = None

    @action(methods=["GET"], detail=False)
    def properties(self, request: request.Request, **kw):
        rows = sync_execute(
            f"""
            SELECT tupleElement(keysAndValues, 1) as key, count(*) as count
            FROM groups
            ARRAY JOIN JSONExtractKeysAndValuesRaw(properties) as keysAndValues
            WHERE team_id = %(team_id)s AND type_id = %(type_id)s
            GROUP BY tupleElement(keysAndValues, 1)
            ORDER BY count DESC, key ASC
        """,
            {"team_id": self.team.pk, "type_id": request.GET["type_id"]},
        )

        return response.Response([{"name": name, "count": count} for name, count in rows])

    @action(methods=["GET"], detail=False)
    def property_values(self, request: request.Request, **kw):
        rows = sync_execute(
            f"""
            SELECT trim(BOTH '"' FROM tupleElement(keysAndValues, 2)) as value
            FROM groups
            ARRAY JOIN JSONExtractKeysAndValuesRaw(properties) as keysAndValues
            WHERE team_id = %(team_id)s AND type_id = %(type_id)s AND tupleElement(keysAndValues, 1) = %(key)s
            GROUP BY tupleElement(keysAndValues, 2)
            ORDER BY value ASC
        """,
            {"team_id": self.team.pk, "type_id": request.GET["type_id"], "key": request.GET["key"]},
        )

        return response.Response([{"name": name} for name in rows])
