import dataclasses
import json
from typing import Any, Optional, cast

from django.db import connection
from loginas.utils import is_impersonated_session
from rest_framework import mixins, request, response, serializers, status, viewsets
from posthog.api.utils import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination

from posthog.api.documentation import extend_schema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.constants import GROUP_TYPES_LIMIT, AvailableFeature
from posthog.event_usage import report_user_action
from posthog.exceptions import EnterpriseFeatureException
from posthog.filters import TermSearchFilterBackend, term_search_filter_sql
from posthog.models import EventProperty, PropertyDefinition, User
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.utils import UUIDT


class SeenTogetherQuerySerializer(serializers.Serializer):
    event_names: serializers.ListField = serializers.ListField(child=serializers.CharField(), required=True)
    property_name: serializers.CharField = serializers.CharField(required=True)


class PropertyDefinitionQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        help_text="Searches properties by name",
        required=False,
        allow_blank=True,
    )

    type = serializers.ChoiceField(
        choices=["event", "person", "group", "session"],
        help_text="What property definitions to return",
        default="event",
    )
    group_type_index = serializers.IntegerField(
        help_text="What group type is the property for. Only should be set if `type=group`",
        required=False,
    )

    properties = serializers.CharField(
        help_text="Comma-separated list of properties to filter",
        required=False,
    )
    is_numerical = serializers.BooleanField(
        help_text="Whether to return only (or excluding) numerical property definitions",
        required=False,
        allow_null=True,
        default=None,
    )
    # :TODO: Move this under `type`
    is_feature_flag = serializers.BooleanField(
        help_text="Whether to return only (or excluding) feature flag properties",
        required=False,
        allow_null=True,
        default=None,
    )
    event_names = serializers.CharField(
        help_text="If sent, response value will have `is_seen_on_filtered_events` populated. JSON-encoded",
        required=False,
    )
    filter_by_event_names = serializers.BooleanField(
        help_text="Whether to return only properties for events in `event_names`",
        required=False,
        allow_null=True,
        default=None,
    )
    excluded_properties = serializers.CharField(
        help_text="JSON-encoded list of excluded properties",
        required=False,
    )

    def validate(self, attrs):
        type_ = attrs.get("type", "event")

        if type_ == "group" and attrs.get("group_type_index") is None:
            raise ValidationError("`group_type_index` must be set for `group` type")

        if type_ != "group" and attrs.get("group_type_index") is not None:
            raise ValidationError("`group_type_index` can only set for `group` type")

        if attrs.get("group_type_index") and not (0 <= attrs.get("group_type_index") < GROUP_TYPES_LIMIT):
            raise ValidationError("Invalid value for `group_type_index`")

        if type_ != "event" and attrs.get("event_names"):
            raise ValidationError("`event_names` can only be set for `event` type")

        return super().validate(attrs)


@dataclasses.dataclass
class QueryContext:
    """
    The raw query is used to both query and count these results
    """

    team_id: int
    table: str
    property_definition_fields: str
    property_definition_table: str

    limit: int
    offset: int

    should_join_event_property: bool = True
    name_filter: str = ""
    numerical_filter: str = ""
    search_query: str = ""
    event_property_filter: str = ""
    event_name_filter: str = ""
    is_feature_flag_filter: str = ""
    excluded_properties_filter: str = ""

    event_property_join_type: str = ""
    event_property_field: str = "NULL"

    # the event name filter is used with and without a posthog_eventproperty_table_join_alias qualifier
    event_name_join_filter: str = ""

    posthog_eventproperty_table_join_alias = "check_for_matching_event_property"

    params: dict = dataclasses.field(default_factory=dict)

    def with_properties_to_filter(self, properties_to_filter: Optional[str]) -> "QueryContext":
        if properties_to_filter:
            return dataclasses.replace(
                self,
                name_filter="AND name = ANY(%(names)s)",
                params={**self.params, "names": properties_to_filter.split(",")},
            )
        else:
            return self

    def with_is_numerical_flag(self, is_numerical: Optional[str]) -> "QueryContext":
        if is_numerical:
            return dataclasses.replace(
                self,
                numerical_filter="AND is_numerical = true AND NOT name = ANY(ARRAY['distinct_id', 'timestamp'])",
            )
        else:
            return self

    def with_feature_flags(self, is_feature_flag: Optional[bool]) -> "QueryContext":
        if is_feature_flag is None:
            return self
        elif is_feature_flag:
            return dataclasses.replace(
                self,
                is_feature_flag_filter="AND (name LIKE %(is_feature_flag_like)s)",
                params={**self.params, "is_feature_flag_like": "$feature/%"},
            )
        elif not is_feature_flag:
            return dataclasses.replace(
                self,
                is_feature_flag_filter="AND (name NOT LIKE %(is_feature_flag_like)s)",
                params={**self.params, "is_feature_flag_like": "$feature/%"},
            )

    def with_type_filter(self, type: str, group_type_index: Optional[int]):
        if type == "event":
            return dataclasses.replace(
                self,
                params={
                    **self.params,
                    "type": PropertyDefinition.Type.EVENT,
                    "group_type_index": -1,
                },
            )
        elif type == "person":
            return dataclasses.replace(
                self,
                should_join_event_property=False,
                params={
                    **self.params,
                    "type": PropertyDefinition.Type.PERSON,
                    "group_type_index": -1,
                },
            )
        elif type == "group":
            return dataclasses.replace(
                self,
                should_join_event_property=False,
                params={
                    **self.params,
                    "type": PropertyDefinition.Type.GROUP,
                    "group_type_index": group_type_index,
                },
            )
        elif type == "session":
            return dataclasses.replace(
                self,
                should_join_event_property=False,
                params={
                    **self.params,
                    "type": PropertyDefinition.Type.SESSION,
                    "group_type_index": -1,
                },
            )

    def with_event_property_filter(
        self, event_names: Optional[str], filter_by_event_names: Optional[bool]
    ) -> "QueryContext":
        event_property_filter = ""
        event_name_filter = ""
        event_property_field = "NULL"
        event_name_join_filter = ""

        # Passed as JSON instead of duplicate properties like event_names[] to work with frontend's combineUrl
        if event_names:
            event_names = json.loads(event_names)

        if event_names and len(event_names) > 0:
            event_property_field = f"{self.posthog_eventproperty_table_join_alias}.property IS NOT NULL"
            event_name_join_filter = "AND event = ANY(%(event_names)s)"

        return dataclasses.replace(
            self,
            event_property_filter=event_property_filter,
            event_property_field=event_property_field,
            event_name_join_filter=event_name_join_filter,
            event_name_filter=event_name_filter,
            event_property_join_type="INNER JOIN" if filter_by_event_names else "LEFT JOIN",
            params={**self.params, "event_names": list(map(str, event_names or []))},
        )

    def with_search(self, search_query: str, search_kwargs: dict) -> "QueryContext":
        return dataclasses.replace(
            self,
            search_query=search_query,
            params={**self.params, "team_id": self.team_id, **search_kwargs},
        )

    def with_excluded_properties(self, excluded_properties: Optional[str], type: str) -> "QueryContext":
        if excluded_properties:
            excluded_properties = json.loads(excluded_properties)

        excluded_list = list(
            set.union(
                set(excluded_properties or []),
                EVENTS_HIDDEN_PROPERTY_DEFINITIONS if type == "event" else [],
            )
        )
        return dataclasses.replace(
            self,
            excluded_properties_filter=(
                f"AND NOT {self.property_definition_table}.name = ANY(%(excluded_properties)s)"
                if len(excluded_list) > 0
                else ""
            ),
            params={
                **self.params,
                "excluded_properties": excluded_list,
            },
        )

    def as_sql(self, order_by_verified: bool):
        verified_ordering = "verified DESC NULLS LAST," if order_by_verified else ""
        query = f"""
            SELECT {self.property_definition_fields}, {self.event_property_field} AS is_seen_on_filtered_events
            FROM {self.table}
            {self._join_on_event_property()}
            WHERE {self.property_definition_table}.team_id = %(team_id)s
              AND type = %(type)s
              AND coalesce(group_type_index, -1) = %(group_type_index)s
              {self.excluded_properties_filter}
             {self.name_filter} {self.numerical_filter} {self.search_query} {self.event_property_filter} {self.is_feature_flag_filter}
             {self.event_name_filter}
            ORDER BY is_seen_on_filtered_events DESC, {verified_ordering} {self.property_definition_table}.name ASC
            LIMIT {self.limit} OFFSET {self.offset}
            """

        return query

    def as_count_sql(self):
        query = f"""
            SELECT count(*) as full_count
            FROM {self.table}
            {self._join_on_event_property()}
            WHERE {self.property_definition_table}.team_id = %(team_id)s
              AND type = %(type)s
              AND coalesce(group_type_index, -1) = %(group_type_index)s
             {self.excluded_properties_filter} {self.name_filter} {self.numerical_filter} {self.search_query} {self.event_property_filter} {self.is_feature_flag_filter}
             {self.event_name_filter}
            """

        return query

    def _join_on_event_property(self):
        return (
            f"""
            {self.event_property_join_type} (
                SELECT DISTINCT property
                FROM posthog_eventproperty
                WHERE team_id = %(team_id)s {self.event_name_join_filter}
            ) {self.posthog_eventproperty_table_join_alias}
            ON {self.posthog_eventproperty_table_join_alias}.property = name
            """
            if self.should_join_event_property
            else ""
        )


# See frontend/src/lib/taxonomy.tsx for where this came from and see
# frontend/scripts/print_property_name_aliases.ts for how to regenerate
PROPERTY_NAME_ALIASES = {
    "$autocapture_disabled_server_side": "Autocapture Disabled Server-Side",
    "$client_session_initial_referring_host": "Referrer Host",
    "$client_session_initial_utm_content": "Initial UTM Source",
    "$client_session_initial_utm_term": "Initial UTM Source",
    "$console_log_recording_enabled_server_side": "Console Log Recording Enabled Server-Side",
    "$el_text": "Element Text",
    "$exception_colno": "Exception source column number",
    "$exception_handled": "Exception was handled",
    "$exception_lineno": "Exception source line number",
    "$geoip_disable": "GeoIP Disabled",
    "$geoip_time_zone": "Timezone",
    "$group_0": "Group 1",
    "$group_1": "Group 2",
    "$group_2": "Group 3",
    "$group_3": "Group 4",
    "$group_4": "Group 5",
    "$ip": "IP Address",
    "$lib": "Library",
    "$lib_custom_api_host": "Library Custom API Host",
    "$lib_version": "Library Version",
    "$lib_version__major": "Library Version (Major)",
    "$lib_version__minor": "Library Version (Minor)",
    "$lib_version__patch": "Library Version (Patch)",
    "$performance_raw": "Browser Performance",
    "$referrer": "Referrer URL",
    "$selected_content": "Copied content",
    "$session_recording_recorder_version_server_side": "Session Recording Recorder Version Server-Side",
    "$user_agent": "Raw User Agent",
    "build": "App Build",
    "previous_build": "App Previous Build",
    "previous_version": "App Previous Version",
    "referring_application": "Referrer Application",
    "version": "App Version",
}


def add_name_alias_to_search_query(search_term: str):
    if not search_term:
        return ""

    normalised_search_term = search_term.lower()
    search_words = normalised_search_term.split()

    entries = [
        f"'{key}'"
        for (key, value) in PROPERTY_NAME_ALIASES.items()
        if all(word in value.lower() for word in search_words)
    ]

    if not entries:
        return ""
    return f"""OR name = ANY(ARRAY[{", ".join(entries)}])"""


def add_latest_means_not_initial(search_term: str):
    trigger_word = "latest"
    opposite_word = "initial"

    if not search_term:
        return ""

    normalised_search_term = search_term.lower()
    search_words = normalised_search_term.split()

    if any(word in trigger_word for word in search_words):
        return f" OR NOT name ilike '%%{opposite_word}%%'"

    return ""


# Event properties generated by ingestion we don't want to show to users
EVENTS_HIDDEN_PROPERTY_DEFINITIONS = set(
    [
        # distinct_id is set in properties by some libraries, but not consistently, so we shouldn't allow users to filter on it
        "distinct_id",
        # used for updating properties
        "$set",
        "$set_once",
        # posthog-js used to send it on events and shouldn't have, now it confuses users
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
            "property_type",
            "tags",
            # This is a calculated property, set when property has been seen with the provided `event_names` query param events. NULL if no `event_names` provided
            "is_seen_on_filtered_events",
        )

    def update(self, property_definition: PropertyDefinition, validated_data):
        changed_fields = {
            k: v
            for k, v in validated_data.items()
            if validated_data.get(k) != getattr(property_definition, k, None if k != "tags" else [])
        }
        # free users can update property type but no other properties on property definitions
        if set(changed_fields) == {"property_type"}:
            changed_fields["updated_by"] = self.context["request"].user
            if changed_fields["property_type"] == "Numeric":
                changed_fields["is_numerical"] = True
            else:
                changed_fields["is_numerical"] = False

            return super().update(property_definition, changed_fields)
        else:
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

    def paginate_queryset(self, queryset, request, view=None) -> Optional[list[Any]]:
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
    TeamAndOrgViewSetMixin,
    TaggedItemViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "property_definition"
    serializer_class = PropertyDefinitionSerializer
    lookup_field = "id"
    filter_backends = [TermSearchFilterBackend]
    ordering = "name"
    search_fields = ["name"]
    pagination_class = NotCountingLimitOffsetPaginator
    queryset = PropertyDefinition.objects.all()

    def dangerously_get_queryset(self):
        queryset = PropertyDefinition.objects.all()
        property_definition_fields = ", ".join(
            [
                f'posthog_propertydefinition."{f.column}"'
                for f in PropertyDefinition._meta.get_fields()
                if hasattr(f, "column")
            ]
        )

        use_enterprise_taxonomy = self.request.user.organization.is_feature_available(
            AvailableFeature.INGESTION_TAXONOMY
        )
        order_by_verified = False
        if use_enterprise_taxonomy:
            try:
                from ee.models.property_definition import EnterprisePropertyDefinition

                # Prevent fetching deprecated `tags` field. Tags are separately fetched in TaggedItemSerializerMixin
                property_definition_fields = ", ".join(
                    [
                        f'{f.cached_col.alias}."{f.column}"'
                        for f in EnterprisePropertyDefinition._meta.get_fields()
                        if hasattr(f, "column") and f.column not in ["deprecated_tags", "tags"]
                    ]
                )

                queryset = EnterprisePropertyDefinition.objects

                order_by_verified = True
            except ImportError:
                use_enterprise_taxonomy = False

        limit = self.paginator.get_limit(self.request)
        offset = self.paginator.get_offset(self.request)

        query = PropertyDefinitionQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)

        search = query.validated_data.get("search")
        search_extra = add_name_alias_to_search_query(search)

        if query.validated_data.get("type") == "person":
            search_extra += add_latest_means_not_initial(search)

        search_query, search_kwargs = term_search_filter_sql(self.search_fields, search, search_extra)

        query_context = (
            QueryContext(
                team_id=self.team_id,
                table=(
                    "ee_enterprisepropertydefinition FULL OUTER JOIN posthog_propertydefinition ON posthog_propertydefinition.id=ee_enterprisepropertydefinition.propertydefinition_ptr_id"
                    if use_enterprise_taxonomy
                    else "posthog_propertydefinition"
                ),
                property_definition_fields=property_definition_fields,
                property_definition_table="posthog_propertydefinition",
                limit=limit,
                offset=offset,
            )
            .with_type_filter(
                query.validated_data.get("type"),
                query.validated_data.get("group_type_index"),
            )
            .with_properties_to_filter(query.validated_data.get("properties"))
            .with_is_numerical_flag(query.validated_data.get("is_numerical"))
            .with_feature_flags(query.validated_data.get("is_feature_flag"))
            .with_event_property_filter(
                event_names=query.validated_data.get("event_names"),
                filter_by_event_names=query.validated_data.get("filter_by_event_names"),
            )
            .with_search(search_query, search_kwargs)
            .with_excluded_properties(
                query.validated_data.get("excluded_properties"),
                type=query.validated_data.get("type"),
            )
        )

        with connection.cursor() as cursor:
            cursor.execute(query_context.as_count_sql(), query_context.params)
            full_count = cursor.fetchone()[0]

        self.paginator.set_count(full_count)

        return queryset.raw(query_context.as_sql(order_by_verified), params=query_context.params)

    def get_serializer_class(self) -> type[serializers.ModelSerializer]:
        serializer_class = self.serializer_class
        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):
            try:
                from ee.api.ee_property_definition import (
                    EnterprisePropertyDefinitionSerializer,
                )
            except ImportError:
                pass
            else:
                serializer_class = EnterprisePropertyDefinitionSerializer
        return serializer_class

    def safely_get_object(self, queryset):
        id = self.kwargs["id"]
        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):
            try:
                from ee.models.property_definition import EnterprisePropertyDefinition
            except ImportError:
                pass
            else:
                enterprise_property = EnterprisePropertyDefinition.objects.filter(id=id, team_id=self.team_id).first()
                if enterprise_property:
                    return enterprise_property
                non_enterprise_property = PropertyDefinition.objects.get(id=id, team_id=self.team_id)
                new_enterprise_property = EnterprisePropertyDefinition(
                    propertydefinition_ptr_id=non_enterprise_property.id, description=""
                )
                new_enterprise_property.__dict__.update(non_enterprise_property.__dict__)
                new_enterprise_property.save()
                return new_enterprise_property
        return PropertyDefinition.objects.get(id=id, team_id=self.team_id)

    @extend_schema(parameters=[PropertyDefinitionQuerySerializer])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(methods=["GET"], detail=False, required_scopes=["property_definition:read"])
    def seen_together(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        """
        Allows a caller to provide a list of event names and a single property name
        Returns a map of the event names to a boolean representing whether that property has ever been seen with that event_name
        """

        serializer = SeenTogetherQuerySerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)

        matches = EventProperty.objects.filter(
            team_id=self.team_id,
            event__in=serializer.validated_data["event_names"],
            property=serializer.validated_data["property_name"],
        )

        results = {}
        for event_name in serializer.validated_data["event_names"]:
            results[event_name] = matches.filter(event=event_name).exists()

        return response.Response(results)

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        instance: PropertyDefinition = self.get_object()
        instance_id = str(instance.id)
        self.perform_destroy(instance)
        # Casting, since an anonymous use CANNOT access this endpoint
        report_user_action(
            cast(User, request.user),
            "property definition deleted",
            {"name": instance.name, "type": instance.get_type_display()},
        )

        log_activity(
            organization_id=cast(UUIDT, self.organization_id),
            team_id=self.team_id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated_session(self.request),
            item_id=instance_id,
            scope="PropertyDefinition",
            activity="deleted",
            detail=Detail(
                name=cast(str, instance.name),
                type=PropertyDefinition.Type(instance.type).label,
                changes=None,
            ),
        )
        return response.Response(status=status.HTTP_204_NO_CONTENT)
