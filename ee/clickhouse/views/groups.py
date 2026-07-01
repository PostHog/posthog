import json as _json
import base64
from typing import Any, Literal, Optional, cast, overload
from urllib.parse import urlencode

from django.db import IntegrityError
from django.utils import timezone

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from opentelemetry import trace
from rest_framework import mixins, request, response, serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError

from posthog.schema import ProductKey

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.capture import CaptureInternalError, capture_internal
from posthog.api.documentation import extend_schema
from posthog.api.property_value_metrics import PROPERTY_VALUES_DURATION
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.helpers.dashboard_templates import create_group_type_mapping_detail_dashboard
from posthog.helpers.impersonation import is_impersonated
from posthog.models import GroupUsageMetric, PropertyDefinition
from posthog.models.activity_logging.activity_log import Change, Detail, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.group import Group
from posthog.models.group.util import create_group, get_group_by_key, list_groups, raw_create_group_ch, save_group
from posthog.models.group_type_mapping import (
    GROUP_TYPE_MAPPING_SERIALIZER_FIELDS,
    GroupTypeMapping,
    delete_group_type_mapping,
    get_group_type_mapping_instance,
    get_group_types_for_project,
    invalidate_group_types_cache,
    update_group_type_mapping_fields,
)
from posthog.models.user import User
from posthog.personhog_client.converters import GroupTypeMappingResult
from posthog.ph_client import feature_enabled_or_false
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.utils import str_to_bool

from products.event_definitions.backend.models.property_definition import PropertyType
from products.notebooks.backend.facade import api as notebooks
from products.notebooks.backend.facade.content import (
    create_bullet_list,
    create_empty_paragraph,
    create_heading_with_text,
    create_text_content,
)

from ee.clickhouse.queries.related_actors_query import RelatedActorsQuery
from ee.clickhouse.views.exceptions import TriggerGroupIdentifyException

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


def _encode_groups_cursor(created_at_us: int, group_key: str) -> str:
    return base64.urlsafe_b64encode(_json.dumps({"c": created_at_us, "k": group_key}).encode()).decode()


def _decode_groups_cursor(cursor: str) -> tuple[int, str]:
    try:
        data = _json.loads(base64.urlsafe_b64decode(cursor))
        # Pre-deploy cursors keyed the tiebreaker on the PG id ("i") instead of group_key ("k").
        # The new keyset can't honor that boundary (different column, no id in ClickHouse), so treat
        # an old-format cursor as no cursor — restart from the first page, like any invalid cursor.
        if "k" not in data:
            return 0, ""
        raw_ts = int(data.get("c", 0))
        group_key = str(data.get("k", ""))
        if 0 < raw_ts < 1e15:
            raw_ts *= 1000
        return raw_ts, group_key
    except Exception:
        return 0, ""


def detect_group_property_type(value):
    if value is None:
        return PropertyType.String
    elif isinstance(value, bool):
        return PropertyType.Boolean
    elif isinstance(value, int | float):
        return PropertyType.Numeric
    elif isinstance(value, str):
        if value.lower() in ("true", "false"):
            return PropertyType.Boolean
        return PropertyType.String
    return PropertyType.String


def create_property_definition(team_id: int, group_type_index: int, property_name: str, property_value):
    """Create or update PostgreSQL PropertyDefinition for group property"""
    property_type = detect_group_property_type(property_value)
    is_numerical = property_type == PropertyType.Numeric

    PropertyDefinition.objects.update_or_create(
        team_id=team_id,
        name=property_name,
        type=PropertyDefinition.Type.GROUP,
        group_type_index=group_type_index,
        defaults={
            "property_type": property_type.value,
            "is_numerical": is_numerical,
        },
    )


class GroupTypeSerializer(serializers.ModelSerializer, UserAccessControlSerializerMixin):
    class Meta:
        model = GroupTypeMapping
        fields = GROUP_TYPE_MAPPING_SERIALIZER_FIELDS
        read_only_fields = ["group_type", "group_type_index"]


def _group_type_row_to_response(row: dict[str, Any]) -> dict[str, Any]:
    """Shape a get_group_types_for_project row like GroupTypeSerializer output.

    Cache entries written before the personhog converter aligned with the ORM
    .values() shape carry the dashboard id under "detail_dashboard_id" — read
    both keys until those entries age out.
    """
    return {
        "group_type": row["group_type"],
        "group_type_index": row["group_type_index"],
        "name_singular": row.get("name_singular"),
        "name_plural": row.get("name_plural"),
        "detail_dashboard": row.get("detail_dashboard", row.get("detail_dashboard_id")),
        "default_columns": row.get("default_columns"),
        "created_at": row.get("created_at"),
    }


class GroupsTypesViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "group"
    serializer_class = GroupTypeSerializer
    # DRF requires a queryset for model resolution, but all actions are overridden
    # to read via personhog-routed helpers — this queryset is never evaluated.
    queryset = GroupTypeMapping.objects.none()
    pagination_class = None
    sharing_enabled_actions = ["list"]
    lookup_field = "group_type_index"

    @extend_schema(responses={200: GroupTypeSerializer(many=True)})
    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        rows = get_group_types_for_project(self.team.project_id, caller_tag="groups/list")
        return response.Response([_group_type_row_to_response(row) for row in rows])

    @action(detail=False, methods=["PATCH"], name="Update group types metadata")
    def update_metadata(self, request: request.Request, *args, **kwargs):
        for row in cast(list[dict], request.data):
            instance = get_group_type_mapping_instance(
                self.team.project_id,
                row["group_type_index"],
                team=self.team,
                consistency="strong",
                caller_tag="groups/update-metadata",
            )
            serializer = self.get_serializer(instance, data=row)
            serializer.is_valid(raise_exception=True)
            fields: dict[str, Any] = {}
            if "name_singular" in serializer.validated_data:
                fields["name_singular"] = serializer.validated_data["name_singular"]
            if "name_plural" in serializer.validated_data:
                fields["name_plural"] = serializer.validated_data["name_plural"]
            if fields:
                update_group_type_mapping_fields(instance, fields=fields, caller_tag="groups/update-metadata")

        invalidate_group_types_cache(self.team.project_id)
        return self.list(request, *args, **kwargs)

    @action(methods=["PUT"], detail=False)
    def create_detail_dashboard(self, request: request.Request, **kw):
        try:
            group_type_mapping = get_group_type_mapping_instance(
                self.team.project_id,
                request.data["group_type_index"],
                team=self.team,
                consistency="strong",
                caller_tag="groups/create-detail-dashboard",
            )
        except GroupTypeMapping.DoesNotExist:
            raise NotFound(detail="Group type not found")

        if group_type_mapping.detail_dashboard_id:
            return response.Response(
                {"detail": "Dashboard already exists for this group type."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        dashboard = create_group_type_mapping_detail_dashboard(group_type_mapping, request.user)
        update_group_type_mapping_fields(
            group_type_mapping,
            fields={"detail_dashboard_id": dashboard.id},
            caller_tag="groups/create-detail-dashboard",
        )
        invalidate_group_types_cache(self.team.project_id)
        return response.Response(self.get_serializer(group_type_mapping).data)

    def destroy(self, request: request.Request, *args, **kwargs):
        group_type_index = int(kwargs[self.lookup_field])
        try:
            instance = get_group_type_mapping_instance(
                self.team.project_id,
                group_type_index,
                team=self.team,
                consistency="strong",
                caller_tag="groups/destroy",
            )
        except GroupTypeMapping.DoesNotExist:
            raise NotFound(detail="Group type not found")
        delete_group_type_mapping(instance, caller_tag="groups/destroy")
        invalidate_group_types_cache(self.team.project_id)
        return response.Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["PUT"], detail=False)
    def set_default_columns(self, request: request.Request, **kw):
        try:
            group_type_mapping = get_group_type_mapping_instance(
                self.team.project_id,
                request.data["group_type_index"],
                team=self.team,
                consistency="strong",
                caller_tag="groups/set-default-columns",
            )
        except GroupTypeMapping.DoesNotExist:
            raise NotFound(detail="Group type not found")

        update_group_type_mapping_fields(
            group_type_mapping,
            fields={"default_columns": request.data["default_columns"]},
            caller_tag="groups/set-default-columns",
        )
        invalidate_group_types_cache(self.team.project_id)
        return response.Response(self.get_serializer(group_type_mapping).data)


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
        return notebooks.get_group_notebook_short_id(obj.id)


class CreateGroupSerializer(serializers.ModelSerializer):
    group_properties = serializers.JSONField(default=dict, required=False, allow_null=True)

    class Meta:
        model = Group
        fields = ["group_type_index", "group_key", "group_properties"]


class GroupsViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    scope_object = "group"
    # DRF needs a queryset for model/basename resolution, but every action is overridden
    # to read via personhog-routed helpers — this queryset is never evaluated against the DB.
    queryset = Group.objects.none()
    pagination_class = None
    serializer_classes = {
        "find": FindGroupSerializer,
        "default": GroupSerializer,
    }

    def get_serializer_class(self):
        return self.serializer_classes.get(self.action, self.serializer_classes["default"])

    @overload
    def _safely_get_query_params(self, require_group_key: Literal[True]) -> tuple[str, str]: ...

    @overload
    def _safely_get_query_params(self, require_group_key: bool = ...) -> tuple[str, str | None]: ...

    def _safely_get_query_params(self, require_group_key: bool = False) -> tuple[str, str | None]:
        group_type_index = self.request.GET.get("group_type_index")
        if not group_type_index:
            raise ValidationError({"group_type_index": ["This query parameter is required."]})
        group_key = self.request.GET.get("group_key")
        if require_group_key and not group_key:
            raise ValidationError({"group_key": ["This query parameter is required."]})
        return group_type_index, group_key

    def safely_get_queryset(self, queryset):
        group_type_index, _ = self._safely_get_query_params()
        return queryset.filter(
            group_type_index=group_type_index,
            group_key__icontains=self.request.GET.get("group_key", ""),
        )

    def safely_get_object(self, queryset):
        group_type_index, group_key = self._safely_get_query_params(require_group_key=True)
        group = get_group_by_key(self.team.pk, int(group_type_index), group_key)
        if group is None:
            raise NotFound()
        return group

    def get_group_type_mapping_or_404(self, group_type_index: GroupTypeIndex) -> GroupTypeMappingResult:
        for m in get_group_types_for_project(self.team.project_id, caller_tag="groups/group-type-lookup"):
            if m["group_type_index"] == group_type_index:
                return GroupTypeMappingResult(group_type=m["group_type"], group_type_index=m["group_type_index"])
        raise NotFound()

    def trigger_group_identify(self, group: Group, operation: str, group_properties: Optional[dict] = None):
        group_type_mapping = self.get_group_type_mapping_or_404(cast(GroupTypeIndex, group.group_type_index))
        properties = {
            "$group_type": group_type_mapping.group_type,
            "$group_key": group.group_key,
            "$group_set": group_properties or group.group_properties,
        }
        try:
            result = capture_internal(
                token=self.team.api_token,
                event_name="$groupidentify",
                event_source="ee_ch_views_groups",
                distinct_id=str(self.team.uuid),
                timestamp=timezone.now(),
                properties=properties,
                process_person_profile=False,
            )
            result.raise_for_status()
        except CaptureInternalError as error:
            raise TriggerGroupIdentifyException(
                exception_data={
                    "code": f"Failed to submit {operation} event.",
                    "detail": "capture_http_error",
                    "type": "capture_http_error",
                },
                status_code=error.status_code or 502,
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
                required=False,
            ),
            OpenApiParameter(
                "cursor",
                OpenApiTypes.STR,
                description="Pagination cursor returned in the `next` URL of a previous response",
                required=False,
            ),
            OpenApiParameter(
                "group_key",
                OpenApiTypes.STR,
                description="Filter groups whose key contains this string (case-insensitive)",
                required=False,
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        """
        List all groups of a specific group type. You must pass ?group_type_index= in the URL.
        To get a list of valid group types, call /api/:project_id/groups_types/.

        Uses forward-only keyset pagination via the `cursor` parameter.
        The `previous` field in the response envelope is always null.
        """
        group_type_index_str = self.request.GET.get("group_type_index")
        if not group_type_index_str:
            raise ValidationError(
                {
                    "group_type_index": [
                        "You must pass ?group_type_index= in this URL. To get a list of valid group types, call /api/:project_id/groups_types/."
                    ]
                }
            )
        try:
            group_type_index = int(group_type_index_str)
        except ValueError:
            raise ValidationError({"group_type_index": ["A valid integer is required."]})

        group_search = self.request.GET.get("search", "")
        group_key = self.request.GET.get("group_key", "")

        cursor_created_at_us = 0
        cursor_group_key = ""
        cursor_param = self.request.GET.get("cursor")
        if cursor_param:
            cursor_created_at_us, cursor_group_key = _decode_groups_cursor(cursor_param)

        result = list_groups(
            team_id=self.team.pk,
            group_type_index=group_type_index,
            group_key_contains=group_key,
            search=group_search,
            cursor_created_at_us=cursor_created_at_us,
            cursor_group_key=cursor_group_key,
        )

        serializer = self.get_serializer(result.groups, many=True)

        next_url = None
        if result.has_more and result.groups:
            last = result.groups[-1]
            cursor = _encode_groups_cursor(int(last.created_at.timestamp() * 1_000_000), last.group_key)
            params: dict[str, str | int] = {"group_type_index": group_type_index, "cursor": cursor}
            if group_search:
                params["search"] = group_search
            if group_key:
                params["group_key"] = group_key
            next_url = request.build_absolute_uri(f"{request.path}?{urlencode(params)}")

        return response.Response({"next": next_url, "previous": None, "results": serializer.data})

    @extend_schema(request=CreateGroupSerializer, responses={status.HTTP_201_CREATED: serializer_classes["default"]})
    def create(self, request, *args, **kwargs):
        request_data = CreateGroupSerializer(data=request.data)
        request_data.is_valid(raise_exception=True)

        group_key = request_data.validated_data["group_key"]
        group_type_index = request_data.validated_data["group_type_index"]

        # Personhog upserts on duplicate (team, group_type_index, group_key) instead
        # of raising, so reject duplicates up front to preserve the 400 contract.
        if get_group_by_key(self.team.pk, group_type_index, group_key) is not None:
            raise ValidationError({"detail": "A group with this key already exists"})

        try:
            group = create_group(
                group_key=group_key,
                group_type_index=group_type_index,
                properties=request_data.validated_data["group_properties"],
                team_id=self.team.pk,
                timestamp=timezone.now(),
            )
        except IntegrityError as exc:
            # Check for both constraint names: Django model name and actual database constraint name
            if "unique team_id/group_key/group_type_index combo" in str(
                exc
            ) or "unique_team_group_key_group_type" in str(exc):
                raise ValidationError({"detail": "A group with this key already exists"})
            raise

        try:
            self.trigger_group_identify(group=group, operation="group create")
        except TriggerGroupIdentifyException as exc:
            return response.Response(data=exc.exception_data, status=exc.status_code)

        for prop_name, prop_value in group.group_properties.items():
            create_property_definition(
                team_id=self.team.pk,
                group_type_index=group.group_type_index,
                property_name=prop_name,
                property_value=prop_value,
            )

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
                was_impersonated=is_impersonated(request),
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
            OpenApiParameter(
                "skip_create_notebook",
                OpenApiTypes.BOOL,
                description="When true, do not lazily create the group's CRM notebook. "
                "Use for read-only lookups (e.g. resolving a group's display name) that should not have side effects.",
                required=False,
            ),
        ]
    )
    @action(methods=["GET"], detail=False, required_scopes=["group:read"])
    def find(self, request: request.Request, **kw) -> response.Response:
        group_type_index, group_key = self._safely_get_query_params(require_group_key=True)
        skip_create_notebook = str_to_bool(request.GET.get("skip_create_notebook"))
        group = get_group_by_key(self.team.pk, int(group_type_index), group_key)
        if group is None:
            raise NotFound()
        if (
            not skip_create_notebook
            and self._is_crm_enabled(cast(User, request.user))
            and not notebooks.group_has_notebook(group.id)
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
            property_key = request.data.get("key")
            property_value = request.data.get("value")
            if not property_key:
                raise ValidationError({"key": ["This field is required."]})
            if property_value is None:
                raise ValidationError({"value": ["This field is required."]})
            create_or_update = "update" if property_key in group.group_properties else "create"
            original_value = group.group_properties.get(property_key, None)
            group.group_properties[property_key] = property_value
            save_group(group, operation="group_update_property")

            create_property_definition(
                team_id=self.team.pk,
                group_type_index=group.group_type_index,
                property_name=property_key,
                property_value=property_value,
            )

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

            try:
                self.trigger_group_identify(
                    group=group,
                    operation=f"group property {create_or_update}",
                    group_properties={property_key: property_value},
                )
            except TriggerGroupIdentifyException as exc:
                return response.Response(data=exc.exception_data, status=exc.status_code)

            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
                item_id=group.pk,
                scope="Group",
                activity=f"{create_or_update}_property",
                detail=Detail(
                    name=str(property_key),
                    changes=[
                        Change(
                            type="Group",
                            action="created" if create_or_update == "create" else "changed",
                            before=original_value,
                            after=property_value,
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
            property_key = request.data.get("$unset")
            if not isinstance(property_key, str):
                raise ValidationError(
                    {"$unset": ["This field is required and must be a string (the property name to delete)."]}
                )
            if property_key not in group.group_properties:
                raise ValidationError({"$unset": [f"Property '{property_key}' does not exist on this group."]})
            group_type_mapping = self.get_group_type_mapping_or_404(cast(GroupTypeIndex, group.group_type_index))
            original_value = group.group_properties[property_key]
            del group.group_properties[property_key]
            save_group(group, operation="group_delete_property")

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
                "$group_unset": [property_key],
            }

            try:
                routed_result = capture_internal(
                    token=self.team.api_token,
                    event_name=event_name,
                    event_source="ee_ch_views_groups",
                    distinct_id=team_uuid_as_distinct_id,
                    timestamp=timestamp,
                    properties=properties,
                    process_person_profile=False,
                )
                routed_result.raise_for_status()

            except CaptureInternalError as e:
                return response.Response(
                    {
                        "attr": "$unset",
                        "code": "Failed to submit group property deletion event.",
                        "detail": "capture_http_error",
                        "type": "capture_http_error",
                    },
                    status=e.status_code or 502,
                )
            except Exception:
                return response.Response(
                    {
                        "attr": "$unset",
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
                was_impersonated=is_impersonated(request),
                item_id=group.pk,
                scope="Group",
                activity="update_property",
                detail=Detail(
                    name=str(property_key),
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
        actor_id = request.GET.get("id")
        if not actor_id:
            raise ValidationError({"id": ["This query parameter is required."]})

        results = RelatedActorsQuery(self.team, group_type_index, actor_id).run()
        return response.Response(results)

    @action(methods=["GET"], detail=False, required_scopes=["group:read"])
    def property_values(self, request: request.Request, **kw):
        with (
            PROPERTY_VALUES_DURATION.labels(endpoint_type="group").time(),
            tracer.start_as_current_span("groups_api_property_values") as span,
        ):
            value_filter = request.GET.get("value")
            group_type_index = request.GET.get("group_type_index")
            if not group_type_index:
                raise ValidationError({"group_type_index": ["This query parameter is required."]})
            key = request.GET.get("key")
            if not key:
                raise ValidationError({"key": ["This query parameter is required."]})

            span.set_attribute("team_id", self.team.pk)
            span.set_attribute("group_type_index", group_type_index)
            span.set_attribute("property_key", key)
            span.set_attribute("has_value_filter", value_filter is not None)

            where_extra = ""
            placeholders: dict[str, ast.Expr] = {
                "group_type_index": ast.Constant(value=int(group_type_index)),
                "key": ast.Constant(value=key),
            }
            if value_filter:
                where_extra = "AND value ILIKE {value_filter}"
                placeholders["value_filter"] = ast.Constant(value=f"%{value_filter}%")

            # Dedup to each group's latest value of the requested property. Aggregating only the
            # extracted property (not the whole properties blob, as the `groups` lazy table would)
            # keeps memory bounded on teams with many large groups.
            # nosemgrep: hogql-fstring-audit (only the constant where_extra fragment is interpolated; key/value/index go through parse_select placeholders)
            query = parse_select(
                f"""
                SELECT value, count(*) AS count
                FROM (
                    SELECT argMax(properties[{{key}}], updated_at) AS value
                    FROM raw_groups
                    WHERE index = {{group_type_index}}
                    GROUP BY index, key
                )
                WHERE value IS NOT NULL
                  {where_extra}
                GROUP BY value
                ORDER BY count DESC, value ASC
                LIMIT 20
                """,
                placeholders=placeholders,
            )

            tag_queries(product=ProductKey.GROUP_ANALYTICS, feature=Feature.QUERY)
            rows = execute_hogql_query(query, team=self.team).results

            span.set_attribute("result_count", len(rows))
            return response.Response(
                {"results": [{"name": name, "count": count} for name, count in rows], "refreshing": False}
            )

    def _is_crm_enabled(self, user: User) -> bool:
        return feature_enabled_or_false(
            "crm-iteration-one",
            str(user.distinct_id),
            groups={"organization": str(self.team.organization.id)},
            group_properties={"organization": {"id": str(self.team.organization.id)}},
            send_feature_flag_events=False,
        )

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
        notebooks.create_group_notebook(self.team.id, group.id, title=notebook_title, content=notebook_content)


_DW_FILTER_REQUIRED_FIELDS = ("table_name", "timestamp_field", "key_field")


class GroupUsageMetricSerializer(serializers.ModelSerializer, UserAccessControlSerializerMixin):
    name = serializers.CharField(
        max_length=255,
        help_text="Name of the usage metric. Must be unique per group type within the project.",
    )
    format = serializers.ChoiceField(
        choices=GroupUsageMetric.Format.choices,
        default=GroupUsageMetric.Format.NUMERIC,
        help_text="How the metric value is formatted in the UI. One of `numeric` or `currency`.",
    )
    interval = serializers.IntegerField(
        default=7,
        help_text="Rolling time window in days used to compute the metric. Defaults to 7.",
    )
    display = serializers.ChoiceField(
        choices=GroupUsageMetric.Display.choices,
        default=GroupUsageMetric.Display.NUMBER,
        help_text="Visual representation in the UI. One of `number` or `sparkline`.",
    )
    filters = serializers.DictField(
        help_text=(
            "Filter definition for the metric. Two shapes are accepted, discriminated by an optional "
            "`source` key.\n\n"
            '**Events** (default, when `source` is missing or `"events"`): HogFunction filter shape — '
            "`events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.\n\n"
            '**Data warehouse** (`source: "data_warehouse"`): `table_name` (synced DW table), '
            "`timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value "
            "matches the entity key). Currently DW metrics only render on group profiles — person profiles "
            "are not yet supported."
        ),
    )
    math = serializers.ChoiceField(
        choices=GroupUsageMetric.Math.choices,
        default=GroupUsageMetric.Math.COUNT,
        help_text=(
            "Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` "
            "on matching events."
        ),
    )
    math_property = serializers.CharField(
        max_length=255,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text=(
            "Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this "
            "is an event property name. For data warehouse metrics this is the column name (or HogQL "
            "expression) to sum on the DW table."
        ),
    )

    class Meta:
        model = GroupUsageMetric
        fields = ("id", "name", "format", "interval", "display", "filters", "math", "math_property")

    def validate(self, data):
        data = super().validate(data)

        math = data.get("math", self.instance.math if self.instance else GroupUsageMetric.Math.COUNT)
        math_property = data.get("math_property", self.instance.math_property if self.instance else None)
        filters = data.get("filters", self.instance.filters if self.instance else None)

        source = (filters or {}).get("source") if isinstance(filters, dict) else None

        if source == GroupUsageMetric.Source.DATA_WAREHOUSE:
            self._validate_data_warehouse(filters, math, math_property)
        elif source in (None, GroupUsageMetric.Source.EVENTS):
            self._validate_events(math, math_property)
        else:
            raise serializers.ValidationError({"filters": f"Unknown source: {source!r}"})

        return data

    def _validate_events(self, math, math_property):
        if math == GroupUsageMetric.Math.SUM and not math_property:
            raise serializers.ValidationError({"math_property": "math_property is required when math is 'sum'."})
        if math == GroupUsageMetric.Math.COUNT and math_property:
            raise serializers.ValidationError({"math_property": "math_property must be empty when math is 'count'."})

    def _validate_data_warehouse(self, filters: dict, math, math_property):
        from products.warehouse_sources.backend.facade.models import DataWarehouseTable

        missing = [field for field in _DW_FILTER_REQUIRED_FIELDS if not filters.get(field)]
        if missing:
            raise serializers.ValidationError(
                {"filters": f"Data warehouse metrics require {', '.join(_DW_FILTER_REQUIRED_FIELDS)}."}
            )

        if math == GroupUsageMetric.Math.SUM and not math_property:
            raise serializers.ValidationError(
                {"math_property": "math_property (column to sum) is required when math is 'sum'."}
            )
        if math == GroupUsageMetric.Math.COUNT and math_property:
            raise serializers.ValidationError({"math_property": "math_property must be empty when math is 'count'."})

        team = self.context["get_team"]()
        if not DataWarehouseTable.objects.filter(team=team, name=filters["table_name"]).exclude(deleted=True).exists():
            raise serializers.ValidationError(
                {"filters": f"Data warehouse table {filters['table_name']!r} does not exist."}
            )


@extend_schema(extensions={"x-product": "customer_analytics"})
class GroupUsageMetricViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "usage_metric"
    queryset = GroupUsageMetric.objects.all()
    serializer_class = GroupUsageMetricSerializer

    def perform_create(self, serializer):
        serializer.save(team=self.team, group_type_index=self.parents_query_dict["group_type_index"])
