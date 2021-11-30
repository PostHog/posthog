from collections import defaultdict

from rest_framework import mixins, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated

from ee.clickhouse.client import sync_execute
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.group import Group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class GroupTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupTypeMapping
        fields = ["group_type", "group_type_index"]


class ClickhouseGroupsTypesView(StructuredViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = GroupTypeSerializer
    queryset = GroupTypeMapping.objects.all().order_by("group_type_index")
    pagination_class = None


class GroupCursorPagination(CursorPagination):
    ordering = "group_key"
    page_size = 100


class GroupSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Group
        fields = [
            "group_type_index",
            "group_key",
            "group_properties",
            "created_at",
        ]


class ClickhouseGroupsView(StructuredViewSetMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = GroupSerializer
    queryset = Group.objects.all()
    pagination_class = GroupCursorPagination
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    lookup_field = "group_key"

    def get_queryset(self):
        return super().get_queryset().filter(group_type_index=self.request.GET["group_type_index"])

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
