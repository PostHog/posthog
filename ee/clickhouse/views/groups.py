import json
from collections import defaultdict

from rest_framework import exceptions, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.group_type_mapping import GroupTypeMapping
import pdb 

class GroupTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupTypeMapping
        fields = ["group_type", "group_type_index"]


class ClickhouseGroupsView(StructuredViewSetMixin, ListModelMixin, viewsets.GenericViewSet):
    serializer_class = GroupTypeSerializer
    queryset = GroupTypeMapping.objects.all()
    pagination_class = None

    def retrieve(self, request, *args, **kwargs):
        instance = sync_execute(
            "SELECT id, team_id, type_id, created_at, properties FROM groups WHERE team_id = %(team_id)s AND group_type_index = %(group_type_index)s AND id = %(id)s",
            {"team_id": self.team_id, "id": self.kwargs["id"], "type_id": self.kwargs["type_id"]},
        )
        if not instance:
            raise exceptions.NotFound(detail="Group not found.")
        serializer = self.serializer_class(instance[0])
        serializer.is_valid()
        return response.Response(serializer.data)
    
    def list(self, request, *args, **kwargs):
        # group_type_mapping = GroupTypeMapping.objects.get(
        #     team_id=self.team_id, type_key=self.kwargs["parent_lookup_type_key"]
        # )
        # instances = (
        #     {
        #         "id": row[0],
        #         "team_id": row[1],
        #         "type_id": row[2],
        #         "created_at": row[3],
        #         "team_id": row[4],
        #         "properties": json.loads(row[5]),
        #     }
            # for row in sync_execute(
        rows = sync_execute(
            """
            SELECT team_id, group_type_index, group_key, created_at, group_properties FROM groups
        """,
            # WHERE team_id = %(team_id)s AND group_type_index = %(group_type_index)s
            # {"team_id": self.team_id, "group_type_index": 1},
        )
        # )
        # pdb.set_trace()
        # serializer = self.serializer_class(data=rows, many=True)
        # serializer.is_valid()
        # return response.Response(serializer.data)

    @action(methods=["GET"], detail=False)
    def property_definitions(self, request: request.Request, **kw):
        rows = sync_execute(
            f"""
            SELECT group_type_index, tupleElement(keysAndValues, 1) as key, count(*) as count
            FROM groups
            ARRAY JOIN JSONExtractKeysAndValuesRaw(group_properties) as keysAndValues
            WHERE team_id = %(team_id)s
            GROUP BY group_type_index, tupleElement(keysAndValues, 1)
            ORDER BY group_type_index ASC, count DESC, key ASC
            """,
            {"team_id": self.team.pk},
        )

        group_type_index_to_properties = defaultdict(list)
        for group_type_index, key, count in rows:
            group_type_index_to_properties[group_type_index].append({"name": key, "count": count})

        return response.Response(group_type_index_to_properties)

    