from collections import defaultdict
from typing import cast

from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import mixins, request, response, serializers, viewsets
from posthog.api.utils import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import CursorPagination

from ee.clickhouse.queries.related_actors_query import RelatedActorsQuery
from posthog.api.documentation import extend_schema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.client import sync_execute
from posthog.models.group import Group
from posthog.models.group_type_mapping import GroupTypeMapping


class GroupTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupTypeMapping
        fields = ["group_type", "group_type_index", "name_singular", "name_plural"]
        read_only_fields = ["group_type", "group_type_index"]


class GroupsTypesViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    scope_object = "group"
    serializer_class = GroupTypeSerializer
    queryset = GroupTypeMapping.objects.all().order_by("group_type_index")
    pagination_class = None
    sharing_enabled_actions = ["list"]

    @action(detail=False, methods=["PATCH"], name="Update group types metadata")
    def update_metadata(self, request: request.Request, *args, **kwargs):
        for row in cast(list[dict], request.data):
            instance = GroupTypeMapping.objects.get(team=self.team, group_type_index=row["group_type_index"])
            serializer = self.get_serializer(instance, data=row)
            serializer.is_valid(raise_exception=True)
            serializer.save()

        return self.list(request, *args, **kwargs)


class GroupCursorPagination(CursorPagination):
    ordering = "-created_at"
    page_size = 100


class GroupSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Group
        fields = ["group_type_index", "group_key", "group_properties", "created_at"]


class GroupsViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    scope_object = "group"
    serializer_class = GroupSerializer
    queryset = Group.objects.all()
    pagination_class = GroupCursorPagination

    def safely_get_queryset(self, queryset):
        return queryset.filter(
            group_type_index=self.request.GET["group_type_index"],
            group_key__icontains=self.request.GET.get("group_key", ""),
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "group_type_index",
                OpenApiTypes.INT,
                description="Specify the group type to list",
                required=True,
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Search the group name",
                required=True,
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        """
        List all groups of a specific group type. You must pass ?group_type_index= in the URL. To get a list of valid group types, call /api/:project_id/groups_types/
        """
        if not self.request.GET.get("group_type_index"):
            raise ValidationError(
                {
                    "group_type_index": [
                        "You must pass ?group_type_index= in this URL. To get a list of valid group types, call /api/:project_id/groups_types/."
                    ]
                }
            )
        queryset = self.filter_queryset(self.get_queryset())

        group_search = self.request.GET.get("search")
        if group_search is not None:
            queryset = queryset.filter(Q(group_properties__icontains=group_search) | Q(group_key__iexact=group_search))

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return response.Response(serializer.data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "group_type_index",
                OpenApiTypes.INT,
                description="Specify the group type to find",
                required=True,
            ),
            OpenApiParameter(
                "group_key",
                OpenApiTypes.STR,
                description="Specify the key of the group to find",
                required=True,
            ),
        ]
    )
    @action(methods=["GET"], detail=False)
    def find(self, request: request.Request, **kw) -> response.Response:
        try:
            group = self.get_queryset().get(group_key=request.GET["group_key"])
            data = self.get_serializer(group).data
            return response.Response(data)
        except Group.DoesNotExist:
            raise NotFound()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "group_type_index",
                OpenApiTypes.INT,
                description="Specify the group type to find",
                required=True,
            ),
            OpenApiParameter(
                "id",
                OpenApiTypes.STR,
                description="Specify the id of the user to find groups for",
                required=True,
            ),
        ]
    )
    @action(methods=["GET"], detail=False)
    def related(self, request: request.Request, pk=None, **kw) -> response.Response:
        group_type_index = request.GET.get("group_type_index")
        id = request.GET["id"]

        results = RelatedActorsQuery(self.team, group_type_index, id).run()
        return response.Response(results)

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
            group_type_index_to_properties[str(group_type_index)].append({"name": key, "count": count})

        return response.Response(group_type_index_to_properties)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "group_type_index",
                OpenApiTypes.INT,
                description="Specify the group type to find property values of",
                required=True,
            ),
            OpenApiParameter(
                "key",
                OpenApiTypes.STR,
                description="Specify the property key to find values for",
                required=True,
            ),
        ]
    )
    @action(methods=["GET"], detail=False)
    def property_values(self, request: request.Request, **kw):
        rows = sync_execute(
            f"""
            SELECT {trim_quotes_expr("tupleElement(keysAndValues, 2)")} as value
            FROM groups
            ARRAY JOIN JSONExtractKeysAndValuesRaw(group_properties) as keysAndValues
            WHERE team_id = %(team_id)s AND group_type_index = %(group_type_index)s AND tupleElement(keysAndValues, 1) = %(key)s
            GROUP BY tupleElement(keysAndValues, 2)
            ORDER BY value ASC
        """,
            {
                "team_id": self.team.pk,
                "group_type_index": request.GET["group_type_index"],
                "key": request.GET["key"],
            },
        )

        return response.Response([{"name": name[0]} for name in rows])
