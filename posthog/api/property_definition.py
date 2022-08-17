import dataclasses
import json
from collections import OrderedDict
from typing import Optional, Type

from django.db import connection
from django.db.models import Prefetch
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.constants import GROUP_TYPES_LIMIT, AvailableFeature
from posthog.exceptions import EnterpriseFeatureException
from posthog.filters import TermSearchFilterBackend, term_search_filter_sql
from posthog.models import PropertyDefinition, TaggedItem
from posthog.permissions import OrganizationMemberPermissions, TeamMemberAccessPermission


@dataclasses.dataclass
class QueryContext:
    """
    The raw query has multiple parameters that change the SQL.
    Particularly
        * what the projection is - it is used to count and to load the models
        * and whether results should be ordered and paged
    """

    projection: str
    table: str
    team_id: int
    name_filter: str
    numerical_filter: str
    search_query: str
    event_property_filter: str
    is_feature_flag_filter: str
    with_paging: bool
    limit: int
    offset: int

    def as_sql(self):
        query = f"""
            SELECT {self.projection}
            FROM {self.table}
            WHERE team_id = {self.team_id} AND name NOT IN %(excluded_properties)s
             {self.name_filter} {self.numerical_filter} {self.search_query} {self.event_property_filter} {self.is_feature_flag_filter}
            """
        if self.with_paging:
            query += f"""
            ORDER BY is_event_property DESC, query_usage_30_day DESC NULLS LAST, name ASC
            LIMIT {self.limit} OFFSET {self.offset}
            """

        return query


# Properties generated by ingestion we don't want to show to users
HIDDEN_PROPERTY_DEFINITIONS = set(
    [
        # distinct_id is set in properties by some libraries
        "distinct_id",
        # used for updating properties
        "$set",
        "$set_once",
        # Group Analytics
        "$groups",
        "$group_type",
        "$group_key",
        "$group_set",
    ]
    + [f"$group_{i}" for i in range(GROUP_TYPES_LIMIT)],
)


class PropertyDefinitionSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = PropertyDefinition
        fields = (
            "id",
            "name",
            "is_numerical",
            "query_usage_30_day",
            "property_type",
            "tags",
            # This is a calculated property, used only when "event_names" is passed to the API.
            "is_event_property",
        )

    def update(self, property_definition: PropertyDefinition, validated_data):
        raise EnterpriseFeatureException()


class NotCountingLimitOffsetPaginator(LimitOffsetPagination):
    """
    The standard LimitOffsetPagination was expensive because there are very many PropertyDefinition models
    And we query them using a RawQuerySet that meant for each page of results we loaded all models twice
    Once to count them and a second time because we would slice them in memory

    This paginator expects the caller to have counted and paged the queryset
    """

    def paginate_queryset(self, queryset, request, view=None):
        if self.count is None:
            raise Exception("count must be manually set before paginating")

        # because this uses a raw query set
        # slicing the query set is being handled outside the paginator
        # and, we don't count the query set
        self.limit = self.get_limit(request)
        if self.limit is None:
            return None

        self.offset = self.get_offset(request)
        self.request = request

        results = list(queryset)

        return results

    def set_count(self, count: int):
        self.count = count

    def get_paginated_response(self, data):
        next_link = self.get_next_link() if data else None
        previous_link = self.get_previous_link()
        return Response(
            OrderedDict([("count", self.count), ("next", next_link), ("previous", previous_link), ("results", data),])
        )

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "example": 123,},
                "next": {
                    "type": "string",
                    "nullable": True,
                    "format": "uri",
                    "example": "http://api.example.org/accounts/?{offset_param}=400&{limit_param}=100".format(
                        offset_param=self.offset_query_param, limit_param=self.limit_query_param
                    ),
                },
                "previous": {
                    "type": "string",
                    "nullable": True,
                    "format": "uri",
                    "example": "http://api.example.org/accounts/?{offset_param}=200&{limit_param}=100".format(
                        offset_param=self.offset_query_param, limit_param=self.limit_query_param
                    ),
                },
                "results": schema,
            },
        }

    def get_next_link(self) -> Optional[str]:
        if self.request is None or self.limit is None:
            return None

        url = self.request.build_absolute_uri()
        url = replace_query_param(url, self.limit_query_param, self.limit)

        if self.offset is None:
            offset = self.limit
        else:
            offset = self.offset + self.limit

        return replace_query_param(url, self.offset_query_param, offset)

    def get_html_context(self):
        return {"previous_url": self.get_previous_link(), "next_url": self.get_next_link()}


class PropertyDefinitionViewSet(
    TaggedItemViewSetMixin,
    StructuredViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = PropertyDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated, OrganizationMemberPermissions, TeamMemberAccessPermission]
    lookup_field = "id"
    filter_backends = [TermSearchFilterBackend]
    ordering = "name"
    search_fields = ["name"]
    pagination_class = NotCountingLimitOffsetPaginator

    def get_queryset(self):
        use_enterprise_taxonomy = self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY)  # type: ignore
        if use_enterprise_taxonomy:
            try:
                from ee.models.property_definition import EnterprisePropertyDefinition
            except ImportError:
                use_enterprise_taxonomy = False

        properties_to_filter = self.request.GET.get("properties", None)
        if properties_to_filter:
            names = tuple(properties_to_filter.split(","))
            name_filter = "AND name IN %(names)s"
        else:
            names = ()
            name_filter = ""

        if self.request.GET.get("is_numerical", None) == "true":
            numerical_filter = "AND is_numerical = true AND name NOT IN ('distinct_id', 'timestamp')"
        else:
            numerical_filter = ""

        if self.request.GET.get("is_feature_flag") == "true":
            is_feature_flag_filter = "AND (name LIKE %(is_feature_flag_like)s)"
        elif self.request.GET.get("is_feature_flag") == "false":
            is_feature_flag_filter = "AND (name NOT LIKE %(is_feature_flag_like)s)"
        else:
            is_feature_flag_filter = ""

        # Passed as JSON instead of duplicate properties like event_names[] to work with frontend's combineUrl
        event_names = self.request.GET.get("event_names", None)
        if event_names:
            event_names = json.loads(event_names)

        # Exclude by name
        excluded_properties = self.request.GET.get("excluded_properties", None)
        if excluded_properties:
            excluded_properties = json.loads(excluded_properties)

        event_property_filter = ""
        if event_names and len(event_names) > 0:
            event_property_field = "(SELECT count(1) > 0 FROM posthog_eventproperty WHERE posthog_eventproperty.team_id=posthog_propertydefinition.team_id AND posthog_eventproperty.event IN %(event_names)s AND posthog_eventproperty.property = posthog_propertydefinition.name)"
            if self.request.GET.get("is_event_property", None) == "true":
                event_property_filter = f"AND {event_property_field} = true"
            elif self.request.GET.get("is_event_property", None) == "false":
                event_property_filter = f"AND {event_property_field} = false"
        else:
            event_property_field = "NULL"

        search = self.request.GET.get("search", None)
        search_query, search_kwargs = term_search_filter_sql(self.search_fields, search)

        params = {
            "event_names": tuple(event_names or []),
            "names": names,
            "excluded_properties": tuple(set.union(set(excluded_properties or []), HIDDEN_PROPERTY_DEFINITIONS)),
            "is_feature_flag_like": "$feature/%",
            **search_kwargs,
        }

        limit = self.paginator.get_limit(self.request)  # type: ignore
        offset = self.paginator.get_offset(self.request)  # type: ignore

        property_definition_fields = ", ".join(
            [f'"{f.column}"' for f in PropertyDefinition._meta.get_fields() if hasattr(f, "column")],  # type: ignore
        )
        if use_enterprise_taxonomy:
            # Prevent fetching deprecated `tags` field. Tags are separately fetched in TaggedItemSerializerMixin
            property_definition_fields = ", ".join(
                [f'"{f.column}"' for f in EnterprisePropertyDefinition._meta.get_fields() if hasattr(f, "column") and f.column not in ["deprecated_tags", "tags"]],  # type: ignore
            )

        qs = (
            EnterprisePropertyDefinition.objects.prefetch_related(
                Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags"),
            )
            if use_enterprise_taxonomy
            else PropertyDefinition.objects
        )

        table = (
            "ee_enterprisepropertydefinition FULL OUTER JOIN posthog_propertydefinition ON posthog_propertydefinition.id=ee_enterprisepropertydefinition.propertydefinition_ptr_id"
            if use_enterprise_taxonomy
            else "posthog_propertydefinition"
        )

        query_context = QueryContext(
            projection=f"{property_definition_fields},{event_property_field} AS is_event_property",
            table=table,
            team_id=self.team_id,
            name_filter=name_filter,
            numerical_filter=numerical_filter,
            search_query=search_query,
            event_property_filter=event_property_filter,
            is_feature_flag_filter=is_feature_flag_filter,
            limit=limit,
            offset=offset,
            with_paging=True,
        )

        query_context_for_count = dataclasses.replace(
            query_context, with_paging=False, projection="count(*) as full_count"
        )
        with connection.cursor() as cursor:
            cursor.execute(query_context_for_count.as_sql(), params)
            full_count = cursor.fetchone()[0]

        self.paginator.set_count(full_count)  # type: ignore

        return qs.raw(query_context.as_sql(), params=params,)

    def get_serializer_class(self) -> Type[serializers.ModelSerializer]:
        serializer_class = self.serializer_class
        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
            try:
                from ee.api.ee_property_definition import EnterprisePropertyDefinitionSerializer
            except ImportError:
                pass
            else:
                serializer_class = EnterprisePropertyDefinitionSerializer  # type: ignore
        return serializer_class

    def get_object(self):
        id = self.kwargs["id"]
        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
            try:
                from ee.models.property_definition import EnterprisePropertyDefinition
            except ImportError:
                pass
            else:
                enterprise_property = EnterprisePropertyDefinition.objects.filter(id=id).first()
                if enterprise_property:
                    return enterprise_property
                non_enterprise_property = PropertyDefinition.objects.get(id=id)
                new_enterprise_property = EnterprisePropertyDefinition(
                    propertydefinition_ptr_id=non_enterprise_property.id, description="",
                )
                new_enterprise_property.__dict__.update(non_enterprise_property.__dict__)
                new_enterprise_property.save()
                return new_enterprise_property
        return PropertyDefinition.objects.get(id=id)
