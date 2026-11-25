import json
import uuid
import functools
import dataclasses
from typing import Any, Optional, Self, Union, cast

from django.db import connections
from django.db.models import Field, Manager, QuerySet, TextChoices
from django.http import Http404
from django.shortcuts import get_object_or_404

from drf_spectacular.utils import OpenApiResponse, extend_schema_field
from opentelemetry import trace
from prometheus_client import Counter
from rest_framework import mixins, request, response, serializers, status, viewsets
from rest_framework.exceptions import ValidationError

from posthog.api.documentation import extend_schema
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import PrecountedLimitOffsetPagination
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.statement_timeout import statement_timeout
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.utils import action
from posthog.constants import GROUP_TYPES_LIMIT
from posthog.event_usage import report_user_action
from posthog.filters import TermSearchFilterBackend, term_search_filter_sql
from posthog.helpers.impersonation import is_impersonated
from posthog.models import User
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.utils import UUIDT
from posthog.settings import EE_AVAILABLE
from posthog.taxonomy.definition_listing import (
    DEFINITION_LIST_STATEMENT_TIMEOUT_MS,
    DefinitionListTimedOut,
    definition_read_db_alias,
)
from posthog.taxonomy.definition_search import search_plan
from posthog.taxonomy.property_last_sent import (
    NOT_TRACKED,
    PropertyLastSent,
    PropertyLastSentMap,
    PropertyLastSentStatus,
    get_property_last_sent_map,
    is_last_sent_tracked,
    snapshot_property_type,
)
from posthog.taxonomy.property_usage import PropertyUsageMap, get_property_usage_map
from posthog.taxonomy.property_usage_ordering import (
    MAX_DEFINITIONS_FOR_USAGE_ORDERING,
    PropertyDefinitionOrdering,
    TooManyPropertiesToOrderByUsage,
    UsedProperty,
    plan_usage_page,
)
from posthog.taxonomy.taxonomy import (
    CORE_FILTER_DEFINITIONS_BY_GROUP,
    PROPERTY_NAME_ALIASES,
    PROPERTY_NAME_ALIASES_BY_TYPE,
    QUERY_DEPRECATED_EVENT_PROPERTIES,
)

from products.event_definitions.backend.models import EventProperty, PropertyDefinition
from products.event_definitions.backend.models.property_definition import effective_project_id_expr

tracer = trace.get_tracer(__name__)

# list of all event properties defined in the taxonomy, that don't start with $
EXCLUDED_EVENT_CORE_PROPERTIES = [
    prop for prop in CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"].keys() if not prop.startswith("$")
]

PROPERTY_DEFINITION_TYPES = ["event", "person", "group", "session"]

PROPERTY_DEFINITIONS_TIMED_OUT_COUNTER = Counter(
    "property_definitions_list_timed_out_total",
    "Property definition list requests cancelled by the statement timeout.",
    labelnames=["property_type"],
)


class PropertyDefinitionsTimedOut(DefinitionListTimedOut):
    default_code = "property_definitions_timeout"
    default_detail = "Loading properties took too long. Try a narrower search, or try again in a moment."


@functools.cache
def property_definition_model(is_enterprise: bool) -> type[PropertyDefinition]:
    """The model the list query runs through, which the enterprise extension replaces."""
    if is_enterprise:
        from ee.models.property_definition import EnterprisePropertyDefinition

        return EnterprisePropertyDefinition
    return PropertyDefinition


def read_db_alias() -> str:
    return definition_read_db_alias(property_definition_model(EE_AVAILABLE))


class SeenTogetherQuerySerializer(serializers.Serializer):
    event_names: serializers.ListField = serializers.ListField(child=serializers.CharField(), required=True)
    property_name: serializers.CharField = serializers.CharField(required=True)


class PropertyDefinitionTypeName(TextChoices):
    # Values match the labels of PropertyDefinition.Type, which stores the type as an integer.
    EVENT = "event"
    PERSON = "person"
    GROUP = "group"
    SESSION = "session"


class PropertyDefinitionTypeSerializerMixin(serializers.Serializer):
    type = serializers.SerializerMethodField(
        help_text="Kind of property: an event, person, group or session property.",
    )
    group_type_index = serializers.SerializerMethodField(
        help_text="Group type index of a group property, null for every other type.",
    )

    @extend_schema_field(serializers.ChoiceField(choices=PropertyDefinitionTypeName.choices))
    def get_type(self, instance: PropertyDefinition) -> str:
        return PropertyDefinitionTypeName(PropertyDefinition.Type(instance.type).label).value

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_group_type_index(self, instance: PropertyDefinition) -> int | None:
        return instance.group_type_index if instance.type == PropertyDefinition.Type.GROUP else None


QUERY_USAGE_MAP_CONTEXT_KEY = "query_usage_map"


class PropertyQueryUsageSerializerMixin(serializers.Serializer):
    # Read from the usage map, never from the deprecated model column of the same name.
    query_usage_30_day = serializers.SerializerMethodField(
        help_text=(
            "Number of query executions in the last 30 days that referenced this property. "
            "Set only when the list request passes `include_query_usage=true` or orders by `query_usage`, "
            "otherwise null."
        ),
    )

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_query_usage_30_day(self, instance: PropertyDefinition) -> int | None:
        usage_map: PropertyUsageMap | None = self.context.get(QUERY_USAGE_MAP_CONTEXT_KEY)
        if usage_map is None:
            return None
        property_type = PropertyDefinitionTypeName(PropertyDefinition.Type(instance.type).label).value
        group_type_index = instance.group_type_index if instance.type == PropertyDefinition.Type.GROUP else None
        if property_type == PropertyDefinitionTypeName.GROUP and group_type_index is None:
            return None
        return usage_map.count_for(property_type, instance.name, group_type_index)


LAST_SENT_CONTEXT_KEY = "last_sent"


class PropertyLastSentSnapshotStatus(TextChoices):
    READY = "ready", "Ready"
    COMPUTING = "computing", "Computing"


@dataclasses.dataclass(frozen=True)
class LastSentContext:
    """What a list request that passed `include_last_sent=true` knows about last-sent dates."""

    snapshot: PropertyLastSentMap | None
    # True while the first snapshot of the type is being built. Then tracked properties have no status yet.
    computing: bool

    def last_sent_for(self, definition: PropertyDefinition) -> PropertyLastSent | None:
        if not is_last_sent_tracked(definition):
            return NOT_TRACKED
        if self.snapshot is None:
            return None
        return self.snapshot.last_sent_for(definition.name)


class PropertyLastSentSerializerMixin(serializers.Serializer):
    last_sent_at = serializers.SerializerMethodField(
        help_text=(
            "When an event or group identify last sent this property, precise to the day. Set only when "
            "`last_sent_status` is `sent`, otherwise null."
        ),
    )
    last_sent_status = serializers.SerializerMethodField(
        help_text=(
            "`sent` when the property was sent in the last 30 days, `not_sent_in_30_days` when it was not, and "
            "`not_tracked` when PostHog does not record it for this property, such as session, virtual and "
            "data warehouse properties. Null when the list request did not pass `include_last_sent=true`, "
            "or while the response's `last_sent.status` is `computing`."
        ),
    )

    def _last_sent(self, instance: PropertyDefinition) -> PropertyLastSent | None:
        context: LastSentContext | None = self.context.get(LAST_SENT_CONTEXT_KEY)
        if context is None:
            return None
        return context.last_sent_for(instance)

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_last_sent_at(self, instance: PropertyDefinition) -> str | None:
        last_sent = self._last_sent(instance)
        if last_sent is None or last_sent.at is None:
            return None
        return serializers.DateTimeField().to_representation(last_sent.at)

    @extend_schema_field(serializers.ChoiceField(choices=PropertyLastSentStatus.choices, allow_null=True))
    def get_last_sent_status(self, instance: PropertyDefinition) -> str | None:
        last_sent = self._last_sent(instance)
        return last_sent.status.value if last_sent is not None else None


MAX_USAGE_METRICS_PROPERTIES = 100


class PropertyUsageEntrySerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=PropertyDefinitionTypeName.choices,
        default=PropertyDefinitionTypeName.EVENT,
        help_text="Property definition type the name belongs to.",
    )
    name = serializers.CharField(
        max_length=400,
        # Names are exact identities, so ` plan` and `plan` are different properties.
        trim_whitespace=False,
        help_text="Property name, for example `$current_url`.",
    )
    group_type_index = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=GROUP_TYPES_LIMIT - 1,
        help_text="Group type index of a group property. Required when `type` is `group`, otherwise omit it.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        group_type_index = attrs.get("group_type_index")
        if attrs["type"] == PropertyDefinitionTypeName.GROUP:
            if group_type_index is None:
                raise ValidationError({"group_type_index": "Group properties need a group type index."})
        elif group_type_index is not None:
            raise ValidationError({"group_type_index": "Only group properties take a group type index."})
        return attrs


class PropertyUsageMetricsRequestSerializer(serializers.Serializer):
    properties = PropertyUsageEntrySerializer(
        many=True,
        help_text=f"Properties to fetch 30-day query usage for, at most {MAX_USAGE_METRICS_PROPERTIES} per request.",
    )

    def validate_properties(self, value: list[dict]) -> list[dict]:
        if not value:
            raise ValidationError("Provide at least one property.")
        if len(value) > MAX_USAGE_METRICS_PROPERTIES:
            raise ValidationError(f"At most {MAX_USAGE_METRICS_PROPERTIES} properties per request.")
        return value


class PropertyUsageMetricsItemSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=PropertyDefinitionTypeName.choices,
        help_text="Property definition type the name belongs to.",
    )
    name = serializers.CharField(help_text="Property name.")
    group_type_index = serializers.IntegerField(
        allow_null=True,
        help_text="Group type index of a group property, null for other types.",
    )
    query_usage_30_day = serializers.IntegerField(
        help_text=(
            "Number of query executions in the last 30 days that referenced this property, "
            "including cached insight views."
        ),
    )


class PropertyUsageFreshnessSerializer(serializers.Serializer):
    computed_at = serializers.DateTimeField(
        help_text="When the counts were computed. They refresh in the background about every 15 minutes.",
    )
    tracking_since = serializers.DateTimeField(
        allow_null=True,
        help_text=(
            "When query usage tracking started for this project, if that is less than 30 days ago. "
            "Then the counts cover only the time since. Null when the counts cover the full 30 days."
        ),
    )


class PropertyUsageMetricsResponseSerializer(PropertyUsageFreshnessSerializer):
    results = PropertyUsageMetricsItemSerializer(
        many=True,
        help_text="One entry per requested property, in request order.",
    )


# Sent as JSON instead of duplicate parameters like event_names[] to work with the frontend's combineUrl
def parse_json_encoded_list(value: str) -> list[str]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        raise ValidationError("Must be a JSON-encoded list of strings")

    if not isinstance(decoded, list) or any(isinstance(item, list | dict) or item is None for item in decoded):
        raise ValidationError("Must be a JSON-encoded list of strings")

    return [str(item) for item in decoded]


class PropertyDefinitionQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        help_text="Searches properties by name",
        required=False,
        allow_blank=True,
    )

    type = serializers.ChoiceField(
        choices=PROPERTY_DEFINITION_TYPES,
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
        help_text=(
            "Whether to return only (or excluding) feature flag properties ($feature/*). "
            "Flags are global, not per-event, so they can't be scoped by event_names/filter_by_event_names — "
            "pass is_feature_flag=true to list them all."
        ),
        required=False,
        allow_null=True,
        default=None,
    )
    event_names = serializers.CharField(
        help_text="If sent, response value will have `is_seen_on_filtered_events` populated. JSON-encoded",
        required=False,
    )
    filter_by_event_names = serializers.BooleanField(
        help_text=(
            "Whether to return only properties for events in `event_names`. "
            "Note: this event scoping does not apply to feature flag properties ($feature/*), which are "
            "global and not tracked per-event; to retrieve feature flags use is_feature_flag=true instead."
        ),
        required=False,
        allow_null=True,
        default=None,
    )
    excluded_properties = serializers.CharField(
        help_text="JSON-encoded list of excluded properties",
        required=False,
    )
    exclude_core_properties = serializers.BooleanField(
        help_text="Whether to exclude core properties",
        required=False,
        default=False,
    )

    exclude_hidden = serializers.BooleanField(
        help_text="Whether to exclude properties marked as hidden",
        required=False,
        default=False,
    )

    exclude_restricted = serializers.BooleanField(
        help_text="Whether to exclude properties that the current user does not have read access to via field-level access control",
        required=False,
        default=False,
    )

    verified = serializers.BooleanField(
        help_text="Filter by verified status. True returns only verified, false returns only unverified.",
        required=False,
        allow_null=True,
        default=None,
    )

    ordering = serializers.ChoiceField(
        choices=PropertyDefinitionOrdering.choices,
        required=False,
        help_text=(
            "Sort by 30-day query count. `-query_usage` puts the most queried properties first, "
            "`query_usage` puts unqueried properties first. Ties sort by name. Both include "
            "`query_usage_30_day` on each result. Refused with a 400 when more than "
            f"{MAX_DEFINITIONS_FOR_USAGE_ORDERING:,} properties match. Omit for the default order."
        ),
    )

    include_query_usage = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Include `query_usage_30_day` on each result and `query_usage` freshness on the response, "
            "without changing the order."
        ),
    )

    include_last_sent = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Include `last_sent_at` and `last_sent_status` on each result and `last_sent` on the response. "
            "When `last_sent.status` is `computing`, request the same page again a few seconds later."
        ),
    )

    def validate_event_names(self, value: str) -> list[str]:
        return parse_json_encoded_list(value)

    def validate_excluded_properties(self, value: str) -> list[str]:
        return parse_json_encoded_list(value)

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


@dataclasses.dataclass(frozen=False)
class QueryContext:
    """
    The raw query is used to both query and count these results
    """

    project_id: int
    table: str
    property_definition_fields: str
    property_definition_table: str

    limit: Optional[int]
    offset: int

    should_join_event_property: bool = True
    name_filter: str = ""
    numerical_filter: str = ""
    search_query: str = ""
    event_property_filter: str = ""
    event_name_filter: str = ""
    is_feature_flag_filter: str = ""
    excluded_properties_filter: str = ""

    order_by_search_relevance: bool = False

    event_property_join_type: str = ""
    event_property_field: str = "NULL"

    # the event name filter is used with and without a posthog_eventproperty_table_join_alias qualifier
    event_name_join_filter: str = ""

    posthog_eventproperty_table_join_alias = "check_for_matching_event_property"

    params: dict = dataclasses.field(default_factory=dict)

    def __post_init__(self):
        # Add limit and offset to params for parameterized query execution
        self.params = {**self.params, "limit": self.limit, "offset": self.offset}

    def with_properties_to_filter(self, properties_to_filter: Optional[str]) -> Self:
        if properties_to_filter:
            return dataclasses.replace(
                self,
                name_filter="AND name = ANY(%(names)s)",
                params={**self.params, "names": properties_to_filter.split(",")},
            )
        else:
            return self

    def with_is_numerical_flag(self, is_numerical: Optional[str]) -> Self:
        if is_numerical:
            return dataclasses.replace(
                self,
                numerical_filter="AND is_numerical = true AND NOT name = ANY(ARRAY['distinct_id', 'timestamp'])",
            )
        else:
            return self

    def with_feature_flags(self, is_feature_flag: Optional[bool]) -> Self:
        if is_feature_flag is None:
            return self
        elif is_feature_flag:
            # Paired with property-defs-rs skip of $feature/* writes to eventproperty.
            # Do not revert without restoring those writes, or the flag picker empties.
            return dataclasses.replace(
                self,
                should_join_event_property=False,
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
        self, event_names: Optional[list[str]], filter_by_event_names: Optional[bool]
    ) -> Self:
        event_property_filter = ""
        event_name_filter = ""
        event_property_field = "NULL"
        event_name_join_filter = ""

        if event_names and self.should_join_event_property:
            event_property_field = f"{self.posthog_eventproperty_table_join_alias}.property IS NOT NULL"
            event_name_join_filter = "AND event = ANY(%(event_names)s)"

        return dataclasses.replace(
            self,
            event_property_filter=event_property_filter,
            event_property_field=event_property_field,
            event_name_join_filter=event_name_join_filter,
            event_name_filter=event_name_filter,
            event_property_join_type="INNER JOIN" if filter_by_event_names else "LEFT JOIN",
            params={**self.params, "event_names": event_names or []},
        )

    def with_search(self, search_query: str, search_kwargs: dict, order_by_search_relevance: bool = False) -> Self:
        return dataclasses.replace(
            self,
            search_query=search_query,
            order_by_search_relevance=order_by_search_relevance,
            params={**self.params, "project_id": self.project_id, **search_kwargs},
        )

    def with_excluded_properties(self, excluded_properties: Optional[list[str]]) -> Self:
        excluded_list = list(set(excluded_properties)) if excluded_properties else []

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

    def with_excluded_core_properties(self, exclude_core_properties: bool, type: str) -> Self:
        if type == "event" and not exclude_core_properties:
            # exclude always excluded event properties
            return dataclasses.replace(
                self,
                excluded_properties_filter=(
                    self.excluded_properties_filter
                    + f"AND NOT {self.property_definition_table}.name = ANY(%(excluded_core_properties)s)"
                ),
                params={**self.params, "excluded_core_properties": list(ALWAYS_EXCLUDED_EVENT_PROPERTIES)},
            )
        elif type == "event" and exclude_core_properties:
            # exclude all properties starting with $ and other event properties defined in the taxonomy
            return dataclasses.replace(
                self,
                excluded_properties_filter=(
                    self.excluded_properties_filter
                    + f"AND NOT {self.property_definition_table}.name LIKE '$%%' AND NOT {self.property_definition_table}.name = ANY(%(excluded_core_properties)s)"
                ),
                params={
                    **self.params,
                    "excluded_core_properties": EXCLUDED_EVENT_CORE_PROPERTIES,
                },
            )
        return self

    def with_verified_filter(self, verified: Optional[bool], use_enterprise_taxonomy: bool) -> Self:
        if verified is not None and use_enterprise_taxonomy:
            if verified:
                verified_filter = " AND ee_enterprisepropertydefinition.verified = true"
            else:
                verified_filter = (
                    " AND (ee_enterprisepropertydefinition.verified IS NULL"
                    " OR ee_enterprisepropertydefinition.verified = false)"
                )
            return dataclasses.replace(
                self,
                excluded_properties_filter=(
                    self.excluded_properties_filter + verified_filter
                    if self.excluded_properties_filter
                    else verified_filter
                ),
            )
        return self

    def with_hidden_filter(self, exclude_hidden: bool, use_enterprise_taxonomy: bool) -> Self:
        if exclude_hidden and use_enterprise_taxonomy:
            hidden_filter = " AND (ee_enterprisepropertydefinition.hidden IS NULL OR ee_enterprisepropertydefinition.hidden = false)"
            return dataclasses.replace(
                self,
                excluded_properties_filter=(
                    self.excluded_properties_filter + hidden_filter
                    if self.excluded_properties_filter
                    else hidden_filter
                ),
            )
        return self

    def with_restricted_filter(self, restricted_property_names: set[str]) -> Self:
        if not restricted_property_names:
            return self
        restricted_filter = f" AND NOT {self.property_definition_table}.name = ANY(%(restricted_properties)s)"
        return dataclasses.replace(
            self,
            excluded_properties_filter=(
                self.excluded_properties_filter + restricted_filter
                if self.excluded_properties_filter
                else restricted_filter
            ),
            params={
                **self.params,
                "restricted_properties": list(restricted_property_names),
            },
        )

    def _from_filtered_sql(self) -> str:
        """The FROM and WHERE clauses that every list statement shares, so all of them see the same rows."""
        return f"""
            FROM {self.table}
            {self._join_on_event_property()}
            WHERE coalesce({self.property_definition_table}.project_id, {self.property_definition_table}.team_id) = %(project_id)s
              AND type = %(type)s
              AND coalesce(group_type_index, -1) = %(group_type_index)s
              {self.excluded_properties_filter}
             {self.name_filter} {self.numerical_filter} {self.search_query} {self.event_property_filter} {self.is_feature_flag_filter}
             {self.event_name_filter}
            """

    def _select_rows_sql(self) -> str:
        return f"SELECT {self.property_definition_fields}, {self.event_property_field} AS is_seen_on_filtered_events"

    def as_sql(self, order_by_verified: bool):
        verified_ordering = "ee_enterprisepropertydefinition.verified DESC NULLS LAST," if order_by_verified else ""
        length_ordering = (
            f"length({self.property_definition_table}.name) ASC," if self.order_by_search_relevance else ""
        )
        return f"""
            {self._select_rows_sql()}
            {self._from_filtered_sql()}
            ORDER BY is_seen_on_filtered_events DESC, {length_ordering} {verified_ordering} {self.property_definition_table}.name ASC
            LIMIT %(limit)s OFFSET %(offset)s
            """

    def as_count_sql(self):
        return f"""
            SELECT count(*) as full_count
            {self._from_filtered_sql()}
            """

    def with_query_usage(self, used_names: list[str]) -> Self:
        return dataclasses.replace(self, params={**self.params, "query_usage_names": used_names})

    def as_used_rows_sql(self) -> str:
        """The id and name of each matching definition that has queries, for the sort in Python."""
        return f"""
            SELECT {self.property_definition_table}.id, {self.property_definition_table}.name
            {self._from_filtered_sql()}
              AND {self.property_definition_table}.name = ANY(%(query_usage_names)s)
            """

    def as_unused_page_sql(self) -> str:
        # NOT EXISTS over unnest() runs as a hash anti-join. `NOT (name = ANY(...))` compares every
        # row against the whole array, which is many times slower for large projects.
        return f"""
            {self._select_rows_sql()}
            {self._from_filtered_sql()}
              AND NOT EXISTS (
                SELECT 1 FROM unnest(%(query_usage_names)s::text[]) AS used_property(name)
                WHERE used_property.name = {self.property_definition_table}.name
              )
            ORDER BY {self.property_definition_table}.name ASC, {self.property_definition_table}.id ASC
            LIMIT %(query_usage_limit)s OFFSET %(query_usage_offset)s
            """

    def as_rows_by_id_sql(self) -> str:
        return f"""
            {self._select_rows_sql()}
            {self._from_filtered_sql()}
              AND {self.property_definition_table}.id = ANY(%(query_usage_ids)s::uuid[])
            """

    def _join_on_event_property(self):
        return (
            f"""
            {self.event_property_join_type} (
                SELECT DISTINCT property
                FROM posthog_eventproperty
                WHERE coalesce(project_id, team_id) = %(project_id)s {self.event_name_join_filter}
            ) {self.posthog_eventproperty_table_join_alias}
            ON {self.posthog_eventproperty_table_join_alias}.property = name
            """
            if self.should_join_event_property
            else ""
        )


def add_name_alias_to_search_query(search_term: str, prop_type: str = "event"):
    if not search_term:
        return ""

    normalised_search_term = search_term.lower()
    search_words = normalised_search_term.split()

    aliases = PROPERTY_NAME_ALIASES_BY_TYPE.get(prop_type, PROPERTY_NAME_ALIASES)

    entries = [f"'{key}'" for (key, value) in aliases.items() if all(word in value.lower() for word in search_words)]

    if not entries:
        return ""
    return f"""OR name = ANY(ARRAY[{", ".join(entries)}])"""


# Event properties generated by ingestion we don't want to show to users
ALWAYS_EXCLUDED_EVENT_PROPERTIES = set(
    [
        # distinct_id is set in properties by some libraries, but not consistently, so we shouldn't allow users to filter on it
        "distinct_id",
        # posthog-js used to send it on events and shouldn't have, now it confuses users
        "$initial_referrer",
        "$initial_referring_domain",
        # Group Analytics
        "$groups",
        "$group_type",
        "$group_key",
        "$group_set",
    ]
    + list(QUERY_DEPRECATED_EVENT_PROPERTIES)
    + [f"$group_{i}" for i in range(GROUP_TYPES_LIMIT)]
    # The $session_entry_X event properties should never be used, the corresponding session property should be used instead.
    # These were added as a workaround for the CDP not supporting true session properties yet.
    + [
        prop
        for prop in CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"].keys()
        if prop.startswith("$session_entry_")
    ]
)


class PropertyDefinitionSerializer(
    PropertyDefinitionTypeSerializerMixin,
    PropertyQueryUsageSerializerMixin,
    PropertyLastSentSerializerMixin,
    TaggedItemSerializerMixin,
    serializers.ModelSerializer,
):
    warehouse_origin = serializers.JSONField(
        read_only=True,
        help_text=(
            "Provenance for a person property populated from a data warehouse source "
            "(source/table/column/last synced), or null. Read-only."
        ),
    )

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
            "warehouse_origin",
            "type",
            "group_type_index",
            "query_usage_30_day",
            "last_sent_at",
            "last_sent_status",
        )

    def validate(self, data):
        validated_data = super().validate(data)

        if "hidden" in validated_data and "verified" in validated_data:
            if validated_data["hidden"] and validated_data["verified"]:
                raise serializers.ValidationError("A property cannot be both hidden and verified")

        return validated_data

    def update(self, property_definition: PropertyDefinition, validated_data: dict):
        # If setting hidden=True, ensure verified becomes false
        if validated_data.get("hidden", False):
            validated_data["verified"] = False
        # If setting verified=True, ensure hidden becomes false
        elif validated_data.get("verified", False):
            validated_data["hidden"] = False

        changed_fields = {
            k: v
            for k, v in validated_data.items()
            if validated_data.get(k) != getattr(property_definition, k, None if k != "tags" else [])
        }
        # free users can update property type but no other properties on property definitions
        if set(changed_fields) == {"property_type"}:
            if changed_fields["property_type"] == "Numeric":
                changed_fields["is_numerical"] = True
            else:
                changed_fields["is_numerical"] = False

            return super().update(property_definition, changed_fields)
        else:
            return super().update(property_definition, validated_data)


class PropertyDefinitionPagination(PrecountedLimitOffsetPagination):
    """Documents the `query_usage` freshness that a list with query counts adds next to the results."""

    def get_paginated_response_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        paginated = super().get_paginated_response_schema(schema)
        paginated["properties"]["query_usage"] = {
            "type": "object",
            "nullable": True,
            "description": (
                "Freshness of `query_usage_30_day`. Present only when the request orders by `query_usage` "
                "or passes `include_query_usage=true`."
            ),
            "properties": {
                "computed_at": {
                    "type": "string",
                    "format": "date-time",
                    "description": PropertyUsageFreshnessSerializer().fields["computed_at"].help_text,
                },
                "tracking_since": {
                    "type": "string",
                    "format": "date-time",
                    "nullable": True,
                    "description": PropertyUsageFreshnessSerializer().fields["tracking_since"].help_text,
                },
            },
            "required": ["computed_at", "tracking_since"],
        }
        paginated["properties"]["last_sent"] = {
            "type": "object",
            "nullable": True,
            "description": "State of `last_sent_at`. Present only when the request passes `include_last_sent=true`.",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": PropertyLastSentSnapshotStatus.values,
                    "description": (
                        "`computing` while the first last-sent snapshot of this property type is being built. "
                        "Request the same page again a few seconds later."
                    ),
                },
                "computed_at": {
                    "type": "string",
                    "format": "date-time",
                    "nullable": True,
                    "description": (
                        "When the last-sent dates were computed. They refresh in the background about every hour."
                    ),
                },
            },
            "required": ["status", "computed_at"],
        }
        return paginated


@extend_schema(extensions={"x-product": "core"})
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
    pagination_class = PropertyDefinitionPagination
    queryset = PropertyDefinition.objects.all()
    query_usage_map: PropertyUsageMap | None = None
    last_sent: LastSentContext | None = None

    @staticmethod
    def _build_virtual_properties(group: str) -> list[dict]:
        return [
            {
                "id": "$builtin_" + key,
                "name": key,
                "description": val.get("description", ""),
                "is_numerical": val["type"] == "Numeric",
                "property_type": val["type"],
                "tags": val.get("tags", []),
                "is_seen_on_filtered_events": True,
                "verified": False,
                "hidden": False,
                "virtual": True,
            }
            for (key, val) in CORE_FILTER_DEFINITIONS_BY_GROUP[group].items()
            if val.get("virtual", False)
        ]

    _BUILTIN_VIRTUAL_PERSON_PROPERTIES = _build_virtual_properties("person_properties")
    _BUILTIN_VIRTUAL_EVENT_PROPERTIES = _build_virtual_properties("event_properties")
    _BUILTIN_VIRTUAL_GROUP_PROPERTIES = _build_virtual_properties("groups")

    def dangerously_get_queryset(self):
        with tracer.start_as_current_span("property_definitions_get_queryset") as span:
            span.set_attribute("team_id", self.team_id)

            queryset: Union[QuerySet[PropertyDefinition], Manager[PropertyDefinition]] = (
                PropertyDefinition.objects.all()
            )
            property_definition_fields = ", ".join(
                [
                    f'posthog_propertydefinition."{f.column}"'
                    for f in PropertyDefinition._meta.get_fields()
                    if isinstance(f, Field) and f.column is not None
                ]
            )

            order_by_verified = False
            if EE_AVAILABLE:
                enterprise_model = property_definition_model(EE_AVAILABLE)

                # Prevent fetching deprecated `tags` field. Tags are separately fetched in TaggedItemSerializerMixin
                property_definition_fields = ", ".join(
                    [
                        f'{f.cached_col.alias}."{f.column}"'
                        for f in enterprise_model._meta.get_fields()
                        if isinstance(f, Field)
                        and f.column is not None
                        and f.column not in ["deprecated_tags", "tags"]
                        and hasattr(f, "cached_col")
                    ]
                )

                queryset = enterprise_model.objects

                order_by_verified = True

            span.set_attribute("ee_available", EE_AVAILABLE)

            assert isinstance(self.paginator, PrecountedLimitOffsetPagination)
            limit = self.paginator.get_limit(self.request)
            offset = self.paginator.get_offset(self.request)

            query = PropertyDefinitionQuerySerializer(data=self.request.query_params)
            query.is_valid(raise_exception=True)

            prop_type = query.validated_data.get("type")
            search = query.validated_data.get("search")
            event_names = query.validated_data.get("event_names")
            filter_by_event_names = query.validated_data.get("filter_by_event_names")

            span.set_attribute("property_type", prop_type or "")
            span.set_attribute("has_search", search is not None and search != "")
            span.set_attribute("event_names_count", len(event_names or []))
            span.set_attribute("filter_by_event_names", bool(filter_by_event_names))
            span.set_attribute("limit", limit or 0)
            span.set_attribute("offset", offset or 0)

            plan = search_plan("posthog_propertydefinition", self.project_id, read_db_alias()) if search else None
            search_extra = add_name_alias_to_search_query(search, prop_type)
            search_query, search_kwargs = term_search_filter_sql(
                self.search_fields, search, search_extra, avoid_trigram_index=plan == "project_scan"
            )

            query_context = (
                QueryContext(
                    project_id=self.project_id,
                    table=(
                        "posthog_propertydefinition LEFT JOIN ee_enterprisepropertydefinition ON posthog_propertydefinition.id=ee_enterprisepropertydefinition.propertydefinition_ptr_id"
                        if EE_AVAILABLE
                        else "posthog_propertydefinition"
                    ),
                    property_definition_fields=property_definition_fields,
                    property_definition_table="posthog_propertydefinition",
                    limit=limit,
                    offset=offset,
                )
                .with_type_filter(
                    prop_type,
                    query.validated_data.get("group_type_index"),
                )
                .with_properties_to_filter(query.validated_data.get("properties"))
                .with_is_numerical_flag(query.validated_data.get("is_numerical"))
                .with_feature_flags(query.validated_data.get("is_feature_flag"))
                .with_event_property_filter(
                    event_names=event_names,
                    filter_by_event_names=filter_by_event_names,
                )
                .with_search(
                    search_query,
                    search_kwargs,
                    order_by_search_relevance=bool(search and search.strip()),
                )
                .with_excluded_properties(query.validated_data.get("excluded_properties"))
                .with_excluded_core_properties(
                    query.validated_data.get("exclude_core_properties", False),
                    type=prop_type,
                )
                .with_hidden_filter(
                    query.validated_data.get("exclude_hidden", False), use_enterprise_taxonomy=EE_AVAILABLE
                )
                .with_restricted_filter(
                    self._get_restricted_property_names(prop_type)
                    if query.validated_data.get("exclude_restricted", False)
                    else set()
                )
                .with_verified_filter(query.validated_data.get("verified"), use_enterprise_taxonomy=EE_AVAILABLE)
            )

            span.set_attribute("joins_event_property", query_context.should_join_event_property)

            with tracer.start_as_current_span("property_definitions_count_query") as count_span:
                with connections[read_db_alias()].cursor() as cursor:
                    cursor.execute(query_context.as_count_sql(), query_context.params)
                    full_count = cursor.fetchone()[0]
                count_span.set_attribute("full_count", full_count)

            self.paginator.set_count(full_count)
            span.set_attribute("full_count", full_count)

            ordering = query.validated_data.get("ordering")
            span.set_attribute("ordering", ordering or "")
            if ordering and full_count > MAX_DEFINITIONS_FOR_USAGE_ORDERING:
                raise TooManyPropertiesToOrderByUsage()
            if ordering or query.validated_data.get("include_query_usage"):
                self.query_usage_map = get_property_usage_map(self.team)
            if query.validated_data.get("include_last_sent"):
                self.last_sent = self._last_sent_context(prop_type, query.validated_data.get("group_type_index"))
            if ordering and self.query_usage_map is not None:
                return self._usage_ordered_page(
                    queryset,
                    query_context,
                    usage_by_name=self.query_usage_map.counts_by_name(
                        prop_type, query.validated_data.get("group_type_index")
                    ),
                    ordering=PropertyDefinitionOrdering(ordering),
                    full_count=full_count,
                    offset=offset or 0,
                    limit=limit if limit is not None else full_count,
                )

            # nosemgrep: python.django.security.audit.custom-expression-as-sql.custom-expression-as-sql (all user input goes through query_context.params)
            return queryset.raw(query_context.as_sql(order_by_verified), params=query_context.params)

    def _usage_ordered_page(
        self,
        queryset: Union[QuerySet[PropertyDefinition], Manager[PropertyDefinition]],
        query_context: QueryContext,
        *,
        usage_by_name: dict[str, int],
        ordering: PropertyDefinitionOrdering,
        full_count: int,
        offset: int,
        limit: int,
    ) -> list[PropertyDefinition]:
        """One page of the list sorted by query count. Every statement applies the same filters."""
        query_context = query_context.with_query_usage(list(usage_by_name))
        used: list[UsedProperty] = []
        if usage_by_name:
            with connections[read_db_alias()].cursor() as cursor:
                cursor.execute(query_context.as_used_rows_sql(), query_context.params)
                used = [
                    UsedProperty(id=uuid.UUID(str(row_id)), name=name, count=usage_by_name[name])
                    for row_id, name in cursor.fetchall()
                ]
        plan = plan_usage_page(ordering, used, full_count, offset, limit)

        used_rows: list[PropertyDefinition] = []
        if plan.used:
            # nosemgrep: python.django.security.audit.custom-expression-as-sql.custom-expression-as-sql (all user input goes through query_context.params)
            fetched = queryset.raw(
                query_context.as_rows_by_id_sql(),
                params={**query_context.params, "query_usage_ids": [str(row.id) for row in plan.used]},
            )
            by_id = {definition.id: definition for definition in fetched}
            used_rows = [by_id[row.id] for row in plan.used if row.id in by_id]

        unused_rows: list[PropertyDefinition] = []
        if plan.unused_limit:
            # nosemgrep: python.django.security.audit.custom-expression-as-sql.custom-expression-as-sql (all user input goes through query_context.params)
            unused_rows = list(
                queryset.raw(
                    query_context.as_unused_page_sql(),
                    params={
                        **query_context.params,
                        "query_usage_limit": plan.unused_limit,
                        "query_usage_offset": plan.unused_offset,
                    },
                )
            )
        return unused_rows + used_rows if plan.unused_first else used_rows + unused_rows

    def _last_sent_context(self, prop_type: str, group_type_index: int | None) -> LastSentContext:
        definition_type = PropertyDefinition.Type[PropertyDefinitionTypeName(prop_type).name]
        property_type = snapshot_property_type(definition_type, group_type_index)
        if property_type is None:
            return LastSentContext(snapshot=None, computing=False)
        snapshot = get_property_last_sent_map(self.team, property_type)
        return LastSentContext(snapshot=snapshot, computing=snapshot is None)

    def filter_queryset(self, queryset):
        if isinstance(queryset, list):
            # The usage-ordered page: SQL already filtered and paged it.
            return queryset
        return super().filter_queryset(queryset)

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        if self.query_usage_map is not None:
            context[QUERY_USAGE_MAP_CONTEXT_KEY] = self.query_usage_map
        if self.last_sent is not None:
            context[LAST_SENT_CONTEXT_KEY] = self.last_sent
        return context

    def get_serializer_class(self) -> type[serializers.ModelSerializer]:
        serializer_class: type[serializers.ModelSerializer] = self.serializer_class
        if EE_AVAILABLE:
            from ee.api.ee_property_definition import EnterprisePropertyDefinitionSerializer

            serializer_class = EnterprisePropertyDefinitionSerializer
        return serializer_class

    def _get_restricted_property_names(self, prop_type: str) -> set[str]:
        """Returns the set of property names that are restricted for the current user and property type."""
        from products.access_control.backend.property_access_control import get_restricted_property_names

        type_map = {
            "event": PropertyDefinition.Type.EVENT,
            "person": PropertyDefinition.Type.PERSON,
            "group": PropertyDefinition.Type.GROUP,
            "session": PropertyDefinition.Type.SESSION,
        }
        pd_type = type_map.get(prop_type)
        if pd_type is None:
            return set()
        user = self.request.user if self.request.user.is_authenticated else None
        return get_restricted_property_names(team_id=self.team_id, user=user, property_type=pd_type)

    def safely_get_object(self, queryset):
        id = self.kwargs["id"]
        # A non-UUID lookup (e.g. the literal "undefined" from a link built without a saved
        # definition id) would raise a ValueError deep in the ORM and surface as a 500. Return a
        # clean 404 instead.
        try:
            uuid.UUID(str(id))
        except ValueError:
            raise Http404("Property definition not found.")
        non_enterprise_property = get_object_or_404(
            PropertyDefinition.objects.alias(effective_project_id=effective_project_id_expr()),
            id=id,
            effective_project_id=self.project_id,
        )
        if EE_AVAILABLE:
            from ee.models.property_definition import EnterprisePropertyDefinition

            enterprise_property = (
                EnterprisePropertyDefinition.objects.alias(effective_project_id=effective_project_id_expr())
                .filter(id=id, effective_project_id=self.project_id)
                .first()
            )
            if enterprise_property:
                return enterprise_property
            # Lazy-create enterprise row if it doesn't exist
            new_enterprise_property = EnterprisePropertyDefinition(
                propertydefinition_ptr_id=non_enterprise_property.id, description=""
            )
            new_enterprise_property.__dict__.update(non_enterprise_property.__dict__)
            new_enterprise_property.save()
            return new_enterprise_property
        return non_enterprise_property

    @extend_schema(parameters=[PropertyDefinitionQuerySerializer])
    def list(self, request, *args, **kwargs):
        event_type = request.query_params.get("type", "event")

        # `event_type` is raw query input, so clamp it to the known set rather than letting a
        # caller mint unbounded Prometheus label values.
        property_type = event_type if event_type in PROPERTY_DEFINITION_TYPES else "unknown"
        with statement_timeout(
            read_db_alias(),
            DEFINITION_LIST_STATEMENT_TIMEOUT_MS,
            PropertyDefinitionsTimedOut,
            PROPERTY_DEFINITIONS_TIMED_OUT_COUNTER.labels(property_type=property_type),
        ):
            response = super().list(request, *args, **kwargs)

        # Inject virtual event/person/group properties to the end of the results
        if event_type in ["event", "person", "group"]:
            paginator = self.paginator
            assert isinstance(paginator, PrecountedLimitOffsetPagination)

            query = PropertyDefinitionQuerySerializer(data=request.query_params)
            query.is_valid(raise_exception=True)

            if event_type == "event":
                virtual_properties = self._BUILTIN_VIRTUAL_EVENT_PROPERTIES
            elif event_type == "person":
                virtual_properties = self._BUILTIN_VIRTUAL_PERSON_PROPERTIES
            else:
                virtual_properties = self._BUILTIN_VIRTUAL_GROUP_PROPERTIES

            restricted_virtual = (
                self._get_restricted_property_names(event_type)
                if query.validated_data.get("exclude_restricted", False)
                else set()
            )
            matching_virtual_props = [
                p for p in virtual_properties if self._filter_virtual_property(p, query, restricted_virtual)
            ]

            db_count = response.data["count"]
            page_end_index = (paginator.offset or 0) + len(response.data["results"])
            is_last_page = page_end_index >= db_count

            # Add virtual properties to the end of the results
            # Technically, this means that the last page can be longer than the others, but as the number of virtual properties is small, this is acceptable
            if self.last_sent is not None:
                # No event carries a virtual property, so its last-sent date is never recorded.
                matching_virtual_props = [
                    {**prop, "last_sent_at": None, "last_sent_status": PropertyLastSentStatus.NOT_TRACKED.value}
                    for prop in matching_virtual_props
                ]
            if is_last_page:
                response.data["results"].extend(matching_virtual_props)

            response.data["count"] = db_count + len(matching_virtual_props)

        if self.query_usage_map is not None:
            response.data["query_usage"] = PropertyUsageFreshnessSerializer(self.query_usage_map).data
        if self.last_sent is not None:
            response.data["last_sent"] = {
                "status": (
                    PropertyLastSentSnapshotStatus.COMPUTING
                    if self.last_sent.computing
                    else PropertyLastSentSnapshotStatus.READY
                ).value,
                "computed_at": (
                    serializers.DateTimeField().to_representation(self.last_sent.snapshot.computed_at)
                    if self.last_sent.snapshot is not None
                    else None
                ),
            }

        return response

    def _filter_virtual_property(
        self,
        prop: dict,
        q: PropertyDefinitionQuerySerializer,
        restricted: set[str] | None = None,
    ) -> bool:
        # Reimplement filtering logic in python for virtual properties
        v = q.validated_data

        # Virtual properties exist for events, persons, and groups
        if v.get("type") not in ["event", "person", "group"]:
            return False

        # explicit name filter  (?properties=a,b,c)
        names = set(v.get("properties", "").split(",")) if v.get("properties") else None
        if names and prop["name"] not in names:
            return False

        # is_numerical flag
        is_num = v.get("is_numerical")
        if is_num is True and not prop["is_numerical"]:
            return False
        if is_num is False and prop["is_numerical"]:
            return False

        # exclusion lists
        excluded = set(v["excluded_properties"]) if v.get("excluded_properties") else set()
        if v.get("exclude_core_properties", False):
            excluded |= set(EXCLUDED_EVENT_CORE_PROPERTIES)
        if prop["name"] in excluded:
            return False

        # text search / aliases
        search = (v.get("search") or "").strip().lower()
        if search:
            words = search.split()
            if not all(w in prop["name"].lower() for w in words):
                # fall back to alias match
                aliases = PROPERTY_NAME_ALIASES_BY_TYPE.get(v.get("type", "event"), PROPERTY_NAME_ALIASES)
                alias = aliases.get(prop["name"])
                if not (alias and all(w in alias.lower() for w in words)):
                    return False

        # hidden filter
        if v.get("exclude_hidden", False) and prop.get("hidden", False):
            return False

        # field-level access control filter
        if v.get("exclude_restricted", False) and restricted and prop["name"] in restricted:
            return False

        # verified filter — virtual properties don't participate in the
        # enterprise verification system, so exclude them whenever the
        # caller explicitly filters by verified status.
        if v.get("verified") is not None:
            return False

        # virtual feature flag filter (not supported anywhere yet but add the logic and tests anyway for completeness)
        if v.get("is_feature_flag") is not None:
            if v["is_feature_flag"]:
                return prop["name"].startswith("$feature/")
            else:
                return not prop["name"].startswith("$feature/")

        return True

    @action(methods=["GET"], detail=False, required_scopes=["property_definition:read"])
    def seen_together(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        """
        Allows a caller to provide a list of event names and a single property name
        Returns a map of the event names to a boolean representing whether that property has ever been seen with that event_name
        """

        serializer = SeenTogetherQuerySerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)

        event_names = serializer.validated_data["event_names"]
        matches = EventProperty.objects.alias(effective_project_id=effective_project_id_expr()).filter(
            effective_project_id=self.project_id,
            event__in=event_names,
            property=serializer.validated_data["property_name"],
        )

        # Single aggregated query instead of one EXISTS per event name — avoids an N+1
        # pattern against posthog_eventproperty that can exceed gateway timeouts on
        # projects with large event-property tables and multi-event filters.
        seen_events = set(matches.values_list("event", flat=True).distinct())
        results = {event_name: event_name in seen_events for event_name in event_names}

        return response.Response(results)

    @validated_request(
        request_serializer=PropertyUsageMetricsRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=PropertyUsageMetricsResponseSerializer,
                description="30-day query usage per requested property.",
            )
        },
        summary="30-day query usage for a set of properties",
        description=(
            "Returns how many query executions referenced each property in the last 30 days, "
            "including cached insight views. Batched: send up to "
            f"{MAX_USAGE_METRICS_PROPERTIES} properties at once. The counts come from the same "
            "per-project snapshot as the property list, which refreshes about every 15 minutes."
        ),
    )
    @action(methods=["POST"], detail=False, required_scopes=["property_definition:read"], url_path="usage_metrics")
    def usage_metrics(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> response.Response:
        usage_map = get_property_usage_map(self.team)
        results = [
            {
                "type": entry["type"],
                "name": entry["name"],
                "group_type_index": entry.get("group_type_index"),
                "query_usage_30_day": usage_map.count_for(entry["type"], entry["name"], entry.get("group_type_index")),
            }
            for entry in request.validated_data["properties"]
        ]
        return response.Response(
            PropertyUsageMetricsResponseSerializer(
                {
                    "results": results,
                    "computed_at": usage_map.computed_at,
                    "tracking_since": usage_map.tracking_since,
                }
            ).data
        )

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        instance: PropertyDefinition = self.get_object()
        instance_id = str(instance.id)
        self.perform_destroy(instance)
        report_user_action(
            request.user,
            "property definition deleted",
            {"name": instance.name, "type": instance.get_type_display()},
            team=self.team,
            request=request,
        )

        log_activity(
            organization_id=cast(UUIDT, self.organization_id),
            team_id=self.team_id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(self.request),
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
