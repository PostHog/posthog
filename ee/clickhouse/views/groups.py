from collections import defaultdict
from typing import Optional, cast

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

import structlog
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from loginas.utils import is_impersonated_session
from requests import HTTPError
from rest_framework import mixins, request, response, serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import CursorPagination

from posthog.api.capture import capture_internal
from posthog.api.documentation import extend_schema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.helpers.dashboard_templates import create_group_type_mapping_detail_dashboard
from posthog.models import GroupUsageMetric
from posthog.models.activity_logging.activity_log import Change, Detail, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.group import Group
from posthog.models.group.util import create_group, raw_create_group_ch
from posthog.models.group_type_mapping import GROUP_TYPE_MAPPING_SERIALIZER_FIELDS, GroupTypeMapping
from posthog.models.user import User

from products.notebooks.backend.models import Notebook, ResourceNotebook
from products.notebooks.backend.util import (
    create_bullet_list,
    create_empty_paragraph,
    create_heading_with_text,
    create_text_content,
)

from ee.clickhouse.queries.related_actors_query import RelatedActorsQuery
from ee.clickhouse.views.exceptions import TriggerGroupIdentifyException

logger = structlog.get_logger(__name__)


class GroupTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupTypeMapping
        fields = GROUP_TYPE_MAPPING_SERIALIZER_FIELDS
        read_only_fields = ["group_type", "group_type_index"]


class GroupsTypesViewSet(
    TeamAndOrgViewSetMixin, mixins.ListModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    scope_object = "group"
    serializer_class = GroupTypeSerializer
    queryset = GroupTypeMapping.objects.all().order_by("group_type_index")
    pagination_class = None
    sharing_enabled_actions = ["list"]
    lookup_field = "group_type_index"
    filter_rewrite_rules = {"project_id": "project_id"}

    def safely_get_queryset(self, queryset):
        return queryset.filter(project_id=self.team.project_id)

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
                project_id=self.team.project_id, group_type_index=request.data["group_type_index"]
            )
        except GroupTypeMapping.DoesNotExist:
            raise NotFound(detail="Group type not found")

        if group_type_mapping.detail_dashboard:
            return response.Response(
                {"detail": "Dashboard already exists for this group type."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        dashboard = create_group_type_mapping_detail_dashboard(group_type_mapping, request.user)
        group_type_mapping.detail_dashboard_id = dashboard.id
        group_type_mapping.save()
        return response.Response(self.get_serializer(group_type_mapping).data)

    @action(methods=["PUT"], detail=False)
    def set_default_columns(self, request: request.Request, **kw):
        try:
            group_type_mapping = GroupTypeMapping.objects.get(
                project_id=self.team.project_id, group_type_index=request.data["group_type_index"]
            )
        except GroupTypeMapping.DoesNotExist:
            raise NotFound(detail="Group type not found")

        group_type_mapping.default_columns = request.data["default_columns"]
        group_type_mapping.save()
        return response.Response(self.get_serializer(group_type_mapping).data)


class GroupCursorPagination(CursorPagination):
    ordering = "-created_at"
    page_size = 100


class GroupSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Group
        fields = ["group_type_index", "group_key", "group_properties", "created_at"]


class FindGroupSerializer(GroupSerializer):
    notebook = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [*GroupSerializer.Meta.fields, "notebook"]

    def get_notebook(self, obj: Group) -> str | None:
        notebooks = ResourceNotebook.objects.filter(group=obj.id).first()
        return notebooks.notebook.short_id if notebooks else None


class CreateGroupSerializer(serializers.ModelSerializer):
    group_properties = serializers.JSONField(default=dict, required=False, allow_null=True)

    class Meta:
        model = Group
        fields = ["group_type_index", "group_key", "group_properties"]


class GroupsViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    scope_object = "group"
    queryset = Group.objects.all()
    pagination_class = GroupCursorPagination
    serializer_classes = {
        "find": FindGroupSerializer,
        "default": GroupSerializer,
    }

    def get_serializer_class(self):
        return self.serializer_classes.get(self.action, self.serializer_classes["default"])

    def safely_get_queryset(self, queryset):
        return queryset.filter(
            group_type_index=self.request.GET["group_type_index"],
            group_key__icontains=self.request.GET.get("group_key", ""),
        )

    def safely_get_object(self, queryset):
        queryset = queryset.filter(
            group_type_index=self.request.GET["group_type_index"],
            group_key=self.request.GET.get("group_key", ""),
        )

        return get_object_or_404(queryset)

    def get_group_type_mapping_or_404(self, group_type_index: GroupTypeIndex) -> GroupTypeMapping:
        try:
            return GroupTypeMapping.objects.get(project_id=self.team.project_id, group_type_index=group_type_index)
        except GroupTypeMapping.DoesNotExist:
            raise NotFound()

    def trigger_group_identify(self, group: Group, operation: str, group_properties: Optional[dict] = None):
        group_type_mapping = self.get_group_type_mapping_or_404(cast(GroupTypeIndex, group.group_type_index))
        properties = {
            "$group_type": group_type_mapping.group_type,
            "$group_key": group.group_key,
            "$group_set": group_properties or group.group_properties,
        }
        try:
            capture_internal(
                token=self.team.api_token,
                event_name="$groupidentify",
                event_source="ee_ch_views_groups",
                distinct_id=str(self.team.uuid),
                timestamp=timezone.now(),
                properties=properties,
                process_person_profile=False,
            ).raise_for_status()
        except HTTPError as error:
            raise TriggerGroupIdentifyException(
                exception_data={
                    "code": f"Failed to submit {operation} event.",
                    "detail": "capture_http_error",
                    "type": "capture_http_error",
                },
                status_code=error.response.status_code,
            )
        except Exception:
            raise TriggerGroupIdentifyException(
                exception_data={
                    "code": f"Failed to submit {operation} event.",
                    "detail": "capture_error",
                    "type": "capture_error",
                },
                status_code=status.HTTP_400_BAD_REQUEST,
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

    @extend_schema(request=CreateGroupSerializer, responses={status.HTTP_201_CREATED: serializer_classes["default"]})
    def create(self, request, *args, **kwargs):
        request_data = CreateGroupSerializer(data=request.data)
        request_data.is_valid(raise_exception=True)

        try:
            group = create_group(
                group_key=request_data.validated_data["group_key"],
                group_type_index=request_data.validated_data["group_type_index"],
                properties=request_data.validated_data["group_properties"],
                team_id=self.team.pk,
                timestamp=timezone.now(),
            )
        except IntegrityError as exc:
            if "unique team_id/group_key/group_type_index combo" in str(exc):
                raise ValidationError({"detail": "A group with this key already exists"})
            raise

        try:
            self.trigger_group_identify(group=group, operation="group create")
        except TriggerGroupIdentifyException as exc:
            return response.Response(data=exc.exception_data, status=exc.status_code)

        details = [
            Detail(
                name=str(name),
                changes=[
                    Change(
                        type="Group",
                        action="created",
                        before=None,
                        after=value,
                    )
                ],
            )
            for name, value in group.group_properties.items()
        ]
        for detail in details:
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated_session(request),
                item_id=group.pk,
                scope="Group",
                activity="create_group",
                detail=detail,
            )

        return response.Response(data=self.get_serializer(group).data, status=status.HTTP_201_CREATED)

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
    @action(methods=["GET"], detail=False, required_scopes=["group:read"])
    def find(self, request: request.Request, **kw) -> response.Response:
        try:
            group = self.get_queryset().get(group_key=request.GET["group_key"])
            if (
                self._is_crm_enabled(cast(User, request.user))
                and not ResourceNotebook.objects.filter(group=group.id).exists()
            ):
                try:
                    self._create_notebook_for_group(group=group)
                except IntegrityError as e:
                    logger.exception(
                        "Group notebook creation failed",
                        group_key=group.group_key,
                        group_type_index=group.group_type_index,
                        team_id=self.team.pk,
                        error=e,
                    )

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
    @action(methods=["POST"], detail=False, required_scopes=["group:write"])
    def update_property(self, request: request.Request, **_kw) -> response.Response:
        try:
            group = self.get_object()
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
            timestamp = timezone.now()
            raw_create_group_ch(
                team_id=self.team.pk,
                group_type_index=group.group_type_index,
                group_key=group.group_key,
                properties=group.group_properties,
                created_at=group.created_at,
                timestamp=timestamp,
            )

            # another internal event submission where we best-effort and don't handle failures...
            try:
                self.trigger_group_identify(
                    group=group,
                    operation="group property update",
                    group_properties={request.data["key"]: request.data["value"]},
                )
            except TriggerGroupIdentifyException as exc:
                return response.Response(data=exc.exception_data, status=exc.status_code)

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
    @action(methods=["POST"], detail=False, required_scopes=["group:write"])
    def delete_property(self, request: request.Request, **_kw) -> response.Response:
        try:
            group = self.get_object()
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
            try:
                group_type_mapping = GroupTypeMapping.objects.get(
                    project_id=self.team.project_id, group_type_index=group.group_type_index
                )
            except GroupTypeMapping.DoesNotExist:
                raise NotFound()
            original_value = group.group_properties[request.data["$unset"]]
            del group.group_properties[request.data["$unset"]]
            group.save()

            # Need to update ClickHouse too
            timestamp = timezone.now()
            raw_create_group_ch(
                team_id=self.team.pk,
                group_type_index=group.group_type_index,
                group_key=group.group_key,
                properties=group.group_properties,
                created_at=group.created_at,
                timestamp=timestamp,
            )

            # another internal event submission where we best-effort and don't handle failures...
            team_uuid_as_distinct_id = str(self.team.uuid)
            event_name = "$delete_group_property"
            properties = {
                "$group_type": group_type_mapping.group_type,
                "$group_key": group.group_key,
                "$group_unset": [request.data["$unset"]],
            }

            try:
                resp = capture_internal(
                    token=self.team.api_token,
                    event_name=event_name,
                    event_source="ee_ch_views_groups",
                    distinct_id=team_uuid_as_distinct_id,
                    timestamp=timestamp,
                    properties=properties,
                    process_person_profile=False,  # don't process person profile
                )
                resp.raise_for_status()

            except HTTPError as e:
                return response.Response(
                    {
                        "attr": key,
                        "code": "Failed to submit group property deletion event.",
                        "detail": "capture_http_error",
                        "type": "capture_http_error",
                    },
                    status=e.response.status_code,
                )
            except Exception:
                return response.Response(
                    {
                        "attr": key,
                        "code": "Failed to submit group property deletion event.",
                        "detail": "capture_error",
                        "type": "capture_error",
                    },
                    status=400,
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
            group = self.get_object()
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
    @action(methods=["GET"], detail=False, required_scopes=["group:read"])
    def related(self, request: request.Request, pk=None, **kw) -> response.Response:
        group_type_index = request.GET.get("group_type_index")
        id = request.GET["id"]

        results = RelatedActorsQuery(self.team, group_type_index, id).run()
        return response.Response(results)

    @action(methods=["GET"], detail=False, required_scopes=["group:read"])
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

    @action(methods=["GET"], detail=False, required_scopes=["group:read"])
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

    def _is_crm_enabled(self, user: User) -> bool:
        return posthoganalytics.feature_enabled(
            "crm-iteration-one",
            str(user.distinct_id),
            groups={"organization": str(self.team.organization.id)},
            group_properties={"organization": {"id": str(self.team.organization.id)}},
            send_feature_flag_events=False,
        )

    @transaction.atomic
    def _create_notebook_for_group(self, group: Group):
        group_name = group.group_properties.get("name", "")
        notebook_title = f"{group_name} Notes" if group_name else "Notes"
        notebook_content = [
            create_heading_with_text(text=notebook_title, level=1),
            create_text_content(
                text="This is a place for you and your team to write collaborative notes about this group"
            ),
            create_empty_paragraph(),
            create_text_content(text="Here's a template to get you started", is_italic=True),
            create_heading_with_text(text="Quick context", level=2),
            create_bullet_list(items=["Industry: ", "Key contacts: ", "Tech stack: "]),
            create_heading_with_text(text="Usage patterns", level=2),
            create_bullet_list(items=["Main use cases: ", "Power features: ", "Blockers: "]),
            create_heading_with_text(text="Last interaction", level=2),
            create_bullet_list(items=["Date: ", "Context: ", "Next steps: "]),
        ]
        notebook = Notebook.objects.create(
            team=self.team,
            title=notebook_title,
            content=notebook_content,
            visibility=Notebook.Visibility.INTERNAL,
        )
        ResourceNotebook.objects.create(notebook=notebook, group=group.id)


class GroupUsageMetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupUsageMetric
        fields = ("id", "name", "format", "interval", "display", "filters")


class GroupUsageMetricViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "group"
    queryset = GroupUsageMetric.objects.all()
    serializer_class = GroupUsageMetricSerializer

    def perform_create(self, serializer):
        serializer.save(team=self.team, group_type_index=self.parents_query_dict["group_type_index"])
