from collections import defaultdict
from django.utils import timezone
from typing import cast

from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import mixins, request, response, serializers, viewsets, status
from posthog.api.capture import capture_internal
from posthog.api.utils import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import CursorPagination

from ee.clickhouse.queries.related_actors_query import RelatedActorsQuery
from posthog.api.documentation import extend_schema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.clickhouse.client import sync_execute
from posthog.helpers.dashboard_templates import create_group_type_mapping_detail_dashboard
from posthog.models.activity_logging.activity_log import Change, Detail, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.group import Group
from posthog.models.group.util import raw_create_group_ch
from posthog.models.group_type_mapping import GroupTypeMapping
from loginas.utils import is_impersonated_session

from posthog.models.user import User


class GroupTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupTypeMapping
        fields = ["group_type", "group_type_index", "name_singular", "name_plural", "detail_dashboard"]
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
            instance = GroupTypeMapping.objects.get(
                project_id=self.team.project_id, group_type_index=row["group_type_index"]
            )
            serializer = self.get_serializer(instance, data=row)
            serializer.is_valid(raise_exception=True)
            serializer.save()

        return self.list(request, *args, **kwargs)

    @action(methods=["PUT"], detail=False)
    def create_detail_dashboard(self, request: request.Request, **kw):
        try:
            group_type_mapping = GroupTypeMapping.objects.get(
                team=self.team, project_id=self.team.project_id, group_type_index=request.data["group_type_index"]
            )
        except GroupTypeMapping.DoesNotExist:
            raise NotFound()

        if group_type_mapping.detail_dashboard:
            return response.Response(
                {"detail": "Dashboard already exists for this group type."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        dashboard = create_group_type_mapping_detail_dashboard(group_type_mapping, request.user)
        group_type_mapping.detail_dashboard = dashboard
        group_type_mapping.save()
        return response.Response(self.get_serializer(group_type_mapping).data)


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
                "group_key",
                OpenApiTypes.STR,
                description="Specify the key of the group to find",
                required=True,
            ),
        ]
    )
    @action(methods=["POST"], detail=False)
    def update_property(self, request: request.Request, **kw) -> response.Response:
        try:
            group = self.get_queryset().get()
            for key in ["value", "key"]:
                if request.data.get(key) is None:
                    return response.Response(
                        {
                            "attr": key,
                            "code": "This field is required.",
                            "detail": "required",
                            "type": "validation_error",
                        },
                        status=400,
                    )
            original_value = group.group_properties.get(request.data["key"], None)
            group.group_properties[request.data["key"]] = request.data["value"]
            group.save()
            # Need to update ClickHouse too
            raw_create_group_ch(
                team_id=self.team.pk,
                group_type_index=group.group_type_index,
                group_key=group.group_key,
                properties=group.group_properties,
                created_at=group.created_at,
                timestamp=timezone.now(),
            )
            capture_internal(
                distinct_id=str(self.team.uuid),
                ip=None,
                site_url=None,
                token=self.team.api_token,
                now=timezone.now(),
                sent_at=None,
                event={
                    "event": "$groupidentify",
                    "properties": {
                        "$group_type_index": group.group_type_index,
                        "$group_key": group.group_key,
                        "$group_set": {request.data["key"]: request.data["value"]},
                    },
                    "distinct_id": str(self.team.uuid),
                    "timestamp": timezone.now().isoformat(),
                },
            )
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated_session(request),
                item_id=group.pk,
                scope="Group",
                activity="update_property",
                detail=Detail(
                    name=str(request.data["key"]),
                    changes=[
                        Change(
                            type="Group",
                            action="created" if original_value is None else "changed",
                            before=original_value,
                            after=request.data["value"],
                        )
                    ],
                ),
            )
            return response.Response(self.get_serializer(group).data)
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
                "group_key",
                OpenApiTypes.STR,
                description="Specify the key of the group to find",
                required=True,
            ),
        ]
    )
    @action(methods=["POST"], detail=False)
    def delete_property(self, request: request.Request, **kw) -> response.Response:
        try:
            group = self.get_queryset().get()
            for key in ["$unset"]:
                if request.data.get(key) is None:
                    return response.Response(
                        {
                            "attr": key,
                            "code": "This field is required.",
                            "detail": "required",
                            "type": "validation_error",
                        },
                        status=400,
                    )
            original_value = group.group_properties[request.data["$unset"]]
            del group.group_properties[request.data["$unset"]]
            group.save()
            # Need to update ClickHouse too
            raw_create_group_ch(
                team_id=self.team.pk,
                group_type_index=group.group_type_index,
                group_key=group.group_key,
                properties=group.group_properties,
                created_at=group.created_at,
                timestamp=timezone.now(),
            )
            capture_internal(
                distinct_id=str(self.team.uuid),
                ip=None,
                site_url=None,
                token=self.team.api_token,
                now=timezone.now(),
                sent_at=None,
                event={
                    "event": "$delete_group_property",
                    "properties": {
                        "$group_type_index": group.group_type_index,
                        "$group_key": group.group_key,
                        "$group_unset": [request.data["$unset"]],
                    },
                    "distinct_id": str(self.team.uuid),
                    "timestamp": timezone.now().isoformat(),
                },
            )
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated_session(request),
                item_id=group.pk,
                scope="Group",
                activity="update_property",
                detail=Detail(
                    name=str(request.data["$unset"]),
                    changes=[Change(type="Group", action="deleted", before=original_value)],
                ),
            )
            return response.Response(self.get_serializer(group).data)
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
    @action(methods=["GET"], detail=False, required_scopes=["activity_log:read"])
    def activity(self, request: request.Request, pk=None, **kwargs):
        try:
            group = self.get_queryset().get()
        except Group.DoesNotExist:
            raise NotFound()

        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(
            scope="Group",
            team_id=self.team_id,
            item_ids=[group.pk],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)

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

    @action(methods=["GET"], detail=False)
    def property_values(self, request: request.Request, **kw):
        value_filter = request.GET.get("value")

        query = f"""
            SELECT {trim_quotes_expr("tupleElement(keysAndValues, 2)")} as value, count(*) as count
            FROM groups
            ARRAY JOIN JSONExtractKeysAndValuesRaw(group_properties) as keysAndValues
            WHERE team_id = %(team_id)s
              AND group_type_index = %(group_type_index)s
              AND tupleElement(keysAndValues, 1) = %(key)s
              {f"AND {trim_quotes_expr('tupleElement(keysAndValues, 2)')} ILIKE %(value_filter)s" if value_filter else ""}
            GROUP BY value
            ORDER BY count DESC, value ASC
            LIMIT 20
        """

        params = {
            "team_id": self.team.pk,
            "group_type_index": request.GET["group_type_index"],
            "key": request.GET["key"],
        }

        if value_filter:
            params["value_filter"] = f"%{value_filter}%"

        rows = sync_execute(query, params)

        return response.Response([{"name": name, "count": count} for name, count in rows])
