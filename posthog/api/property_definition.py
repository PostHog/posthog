import dataclasses
import json
from typing import Any, Dict, List, Optional, Type

from django.db import connection
from django.db.models import Prefetch
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.pagination import LimitOffsetPagination

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
    The raw query is used to both query and count these results
    """

    team_id: int
    table: str
    property_definition_fields: str

    limit: int
    offset: int

    name_filter: str = ""
    numerical_filter: str = ""
    search_query: str = ""
    event_property_filter: str = ""
    is_feature_flag_filter: str = ""

    event_property_field: str = "NULL"

    params: Dict = dataclasses.field(default_factory=dict)

    def with_properties_to_filter(self, properties_to_filter: Optional[str]) -> "QueryContext":
        if properties_to_filter:
            return dataclasses.replace(
                self,
                name_filter="AND name IN %(names)s",
                params={**self.params, "names": tuple(properties_to_filter.split(","))},
            )
        else:
            return self

    def with_is_numerical_flag(self, is_numerical: Optional[str]) -> "QueryContext":
        if is_numerical == "true":
            return dataclasses.replace(
                self, numerical_filter="AND is_numerical = true AND name NOT IN ('distinct_id', 'timestamp')"
            )
        else:
            return self

    def with_feature_flags(self, is_feature_flag: Optional[str]) -> "QueryContext":
        if is_feature_flag == "true":
            return dataclasses.replace(
                self,
                is_feature_flag_filter="AND (name LIKE %(is_feature_flag_like)s)",
                params={**self.params, "is_feature_flag_like": "$feature/%"},
            )
        elif is_feature_flag == "false":
            return dataclasses.replace(
                self,
                is_feature_flag_filter="AND (name NOT LIKE %(is_feature_flag_like)s)",
                params={**self.params, "is_feature_flag_like": "$feature/%"},
            )
        else:
            return self

    def with_event_property_filter(
        self, event_names: Optional[str], is_event_property: Optional[str]
    ) -> "QueryContext":
        event_property_filter = ""
        event_property_field = "NULL"

        # Passed as JSON instead of duplicate properties like event_names[] to work with frontend's combineUrl
        if event_names:
            event_names = json.loads(event_names)

        if event_names and len(event_names) > 0:
            event_property_field = "(SELECT count(1) > 0 FROM posthog_eventproperty WHERE posthog_eventproperty.team_id=posthog_propertydefinition.team_id AND posthog_eventproperty.event IN %(event_names)s AND posthog_eventproperty.property = posthog_propertydefinition.name)"
            if is_event_property == "true":
                event_property_filter = f"AND {event_property_field} = true"
            elif is_event_property == "false":
                event_property_filter = f"AND {event_property_field} = false"

        return dataclasses.replace(
            self,
            event_property_filter=event_property_filter,
            event_property_field=event_property_field,
            params={**self.params, "event_names": tuple(event_names or [])},
        )

    def with_search(self, search_query: str, search_kwargs: Dict) -> "QueryContext":
        return dataclasses.replace(self, search_query=search_query, params={**self.params, **search_kwargs})

    def with_excluded_properties(self, excluded_properties: Optional[str]) -> "QueryContext":
        if excluded_properties:
            excluded_properties = json.loads(excluded_properties)

        return dataclasses.replace(
            self,
            params={
                **self.params,
                "excluded_properties": tuple(set.union(set(excluded_properties or []), HIDDEN_PROPERTY_DEFINITIONS)),
            },
        )

    def as_sql(self):
        query = f"""
            SELECT {self.property_definition_fields},{self.event_property_field} AS is_event_property
            FROM {self.table}
            WHERE team_id = {self.team_id} AND name NOT IN %(excluded_properties)s
             {self.name_filter} {self.numerical_filter} {self.search_query} {self.event_property_filter} {self.is_feature_flag_filter}
            ORDER BY is_event_property DESC, query_usage_30_day DESC NULLS LAST, name ASC
            LIMIT {self.limit} OFFSET {self.offset}
            """

        return query

    def as_count_sql(self):
        query = f"""
            SELECT count(*) as full_count
            FROM {self.table}
            WHERE team_id = {self.team_id} AND name NOT IN %(excluded_properties)s
             {self.name_filter} {self.numerical_filter} {self.search_query} {self.event_property_filter} {self.is_feature_flag_filter}
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
        # posthog-js used to send it and shouldn't have, now it confuses users
        "$initial_referrer",
        "$initial_referring_domain",
        # Group Analytics
        "$groups",
        "$group_type",
        "$group_key",
        "$group_set",
    ]
    + [f"$group_{i}" for i in range(GROUP_TYPES_LIMIT)]
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

    def set_count(self, count: int) -> None:
        self.count = count

    def get_count(self, queryset) -> int:
        """
        Determine an object count, supporting either querysets or regular lists.
        """
        if self.count is None:
            raise Exception("count must be manually set before paginating")

        return self.count

    def paginate_queryset(self, queryset, request, view=None) -> Optional[List[Any]]:
        """
        Assumes the queryset has already had pagination applied
        """
        self.count = self.get_count(queryset)
        self.limit = self.get_limit(request)
        if self.limit is None:
            return None

        self.offset = self.get_offset(request)
        self.request = request

        if self.count == 0 or self.offset > self.count:
            return []

        return list(queryset)


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
        queryset = PropertyDefinition.objects

        property_definition_fields = ", ".join(
            [f'"{f.column}"' for f in PropertyDefinition._meta.get_fields() if hasattr(f, "column")]  # type: ignore
        )

        use_enterprise_taxonomy = self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY)  # type: ignore
        if use_enterprise_taxonomy:
            try:
                from ee.models.property_definition import EnterprisePropertyDefinition

                # Prevent fetching deprecated `tags` field. Tags are separately fetched in TaggedItemSerializerMixin
                property_definition_fields = ", ".join(
                    [
                        f'"{f.column}"'  # type: ignore
                        for f in EnterprisePropertyDefinition._meta.get_fields()
                        if hasattr(f, "column") and f.column not in ["deprecated_tags", "tags"]  # type: ignore
                    ]
                )

                queryset = EnterprisePropertyDefinition.objects.prefetch_related(
                    Prefetch(
                        "tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags"
                    )
                )
            except ImportError:
                use_enterprise_taxonomy = False

        limit = self.paginator.get_limit(self.request)  # type: ignore
        offset = self.paginator.get_offset(self.request)  # type: ignore

        search = self.request.GET.get("search", None)
        search_query, search_kwargs = term_search_filter_sql(self.search_fields, search)

        query_context = (
            QueryContext(
                team_id=self.team_id,
                table=(
                    "ee_enterprisepropertydefinition FULL OUTER JOIN posthog_propertydefinition ON posthog_propertydefinition.id=ee_enterprisepropertydefinition.propertydefinition_ptr_id"
                    if use_enterprise_taxonomy
                    else "posthog_propertydefinition"
                ),
                property_definition_fields=property_definition_fields,
                limit=limit,
                offset=offset,
            )
            .with_properties_to_filter(self.request.GET.get("properties", None))
            .with_is_numerical_flag(self.request.GET.get("is_numerical", None))
            .with_feature_flags(self.request.GET.get("is_feature_flag"))
            .with_event_property_filter(
                event_names=self.request.GET.get("event_names", None),
                is_event_property=self.request.GET.get("is_event_property", None),
            )
            .with_search(search_query, search_kwargs)
            .with_excluded_properties(self.request.GET.get("excluded_properties", None))
        )

        with connection.cursor() as cursor:
            cursor.execute(query_context.as_count_sql(), query_context.params)
            full_count = cursor.fetchone()[0]

        self.paginator.set_count(full_count)  # type: ignore

        return queryset.raw(query_context.as_sql(), params=query_context.params)

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
                    propertydefinition_ptr_id=non_enterprise_property.id, description=""
                )
                new_enterprise_property.__dict__.update(non_enterprise_property.__dict__)
                new_enterprise_property.save()
                return new_enterprise_property
        return PropertyDefinition.objects.get(id=id)
