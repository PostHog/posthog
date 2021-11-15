from collections import defaultdict
from typing import Optional

from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.group import ClickhouseGroupSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.utils import PaginationMode, format_paginated_url
from posthog.models.group_type_mapping import GroupTypeMapping


class GroupTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupTypeMapping
        fields = ["group_type", "group_type_index"]


class ClickhouseGroupsTypesView(StructuredViewSetMixin, ListModelMixin, viewsets.GenericViewSet):
    serializer_class = GroupTypeSerializer
    queryset = GroupTypeMapping.objects.all()
    pagination_class = None


class ClickhouseGroupsView(StructuredViewSetMixin, ListModelMixin, viewsets.GenericViewSet):
    serializer_class = ClickhouseGroupSerializer
    queryset = None
    pagination_class = None

    def list(self, request, *args, **kwargs):
        limit = 100
        offset = int(request.GET.get("offset", 0))

        query_result = sync_execute(
            """
                SELECT group_type_index, group_key, created_at, group_properties FROM groups
                INNER JOIN (
                    SELECT
                        group_key,
                        max(created_at) as created_at
                    FROM groups
                    WHERE team_id = %(team_id)s AND group_type_index = %(group_type_index)s
                    GROUP BY group_key
                    LIMIT 100 OFFSET %(offset)s
                ) latest_groups
                ON groups.group_key == latest_groups.group_key AND groups.created_at == latest_groups.created_at
                WHERE team_id = %(team_id)s AND group_type_index = %(group_type_index)s
                ORDER BY created_at
            """,
            {"team_id": self.team_id, "group_type_index": request.GET["group_type_index"], "offset": offset},
        )
        results = ClickhouseGroupSerializer(query_result, many=True).data
        next_url: Optional[str] = None
        previous_url: Optional[str] = None
        if len(query_result) > limit:
            next_url = format_paginated_url(request, offset, limit)
            previous_url = format_paginated_url(request, offset, limit, mode=PaginationMode.previous)

        return response.Response({"next_url": next_url, "previous_url": previous_url, "results": results})

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

    @action(methods=["GET"], detail=False)
    def property_values(self, request: request.Request, **kw):
        rows = sync_execute(
            f"""
            SELECT trim(BOTH '"' FROM tupleElement(keysAndValues, 2)) as value
            FROM groups
            ARRAY JOIN JSONExtractKeysAndValuesRaw(group_properties) as keysAndValues
            WHERE team_id = %(team_id)s AND group_type_index = %(group_type_index)s AND tupleElement(keysAndValues, 1) = %(key)s
            GROUP BY tupleElement(keysAndValues, 2)
            ORDER BY value ASC
        """,
            {"team_id": self.team.pk, "group_type_index": request.GET["group_type_index"], "key": request.GET["key"]},
        )

        return response.Response([{"name": name[0]} for name in rows])
