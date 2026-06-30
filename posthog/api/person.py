import json
import uuid
import builtins
from datetime import UTC, datetime, timedelta
from typing import Any, List, Optional, TypeVar, Union, cast  # noqa: UP035

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    extend_schema,
    extend_schema_field,
    extend_schema_serializer,
    extend_schema_view,
)
from opentelemetry import trace
from prometheus_client import Counter
from rest_framework import request, response, serializers, viewsets
from rest_framework.exceptions import MethodNotAllowed, NotFound, ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import JSONParser
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.schema import ActorsQuery, ProductKey

from posthog.hogql.constants import CSV_EXPORT_LIMIT

from posthog.api.capture import CaptureInternalError, capture_internal
from posthog.api.documentation import PersonPropertiesSerializer
from posthog.api.property_value_metrics import PROPERTY_VALUES_DURATION
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action, format_paginated_url, get_target_entity
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.constants import INSIGHT_FUNNELS, LIMIT, OFFSET, FunnelVizType
from posthog.decorators import cached_by_filters
from posthog.event_usage import get_request_analytics_properties
from posthog.helpers.impersonation import is_impersonated
from posthog.metrics import LABEL_TEAM_ID
from posthog.models import Filter, Person, Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.filters.lifecycle_filter import LifecycleFilter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.person.bulk_delete import (
    delete_persons_profile,
    queue_person_event_deletion,
    queue_person_recording_deletion,
    resolve_persons_for_deletion,
)
from posthog.models.person.deletion import reset_deleted_person_distinct_ids
from posthog.models.person.missing_person import MissingPerson
from posthog.models.person.util import (
    get_distinct_ids_for_persons,
    get_person_by_pk_or_uuid,
    get_persons_by_uuids,
    get_persons_mapped_by_distinct_id,
)
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.queries.actor_base_query import get_serialized_people
from posthog.queries.properties_timeline import PropertiesTimeline
from posthog.rate_limit import ClickHouseBurstRateThrottle, PersonalApiKeyRateThrottle, UserOrEmailRateThrottle
from posthog.renderers import SafeJSONRenderer
from posthog.tasks.split_person import split_person
from posthog.utils import (
    format_query_params_absolute_url,
    is_anonymous_id,
    refresh_requested_by_client,
    relative_date_parse_with_delta_mapping,
)

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import get_all_cohort_ids_by_person_uuid
from products.product_analytics.backend.api.insight import capture_legacy_api_call
from products.workflows.backend.api.message_assets import (
    MessageAssetSerializer,
    PersonMessageAssetsRequestSerializer,
    fetch_message_assets_for_person,
    workflow_email_assets_ui_enabled,
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

DEFAULT_PAGE_LIMIT = 100
# Sync with .../lib/constants.tsx and .../cdp/utils.ts
# It's almost certainly wrong to add more properties to this list, instead convince the user to send data to use with
# these properties, or use e.g. a CDP transformation to rewrite their events.
#
# If you do want to add new columns
# * add it to the places linked above
# * ensure it is materialized on US and EU prod
# * ensure the materialized columns have case-insensitive skip indexes
# * ensure that the text box search in the Persons scene is searching this column (using the Actors query)

PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES = [
    "email",
    "name",
    "username",
]

API_PERSON_LIST_BYTES_READ_FROM_POSTGRES_COUNTER = Counter(
    "api_person_list_bytes_read_from_postgres",
    "An estimate of how many bytes we've read from postgres to return the person endpoint.",
    labelnames=[LABEL_TEAM_ID],
)


class PersonLimitOffsetPagination(LimitOffsetPagination):
    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "next": {
                    "type": "string",
                    "nullable": True,
                    "format": "uri",
                    "example": "https://app.posthog.com/api/projects/{project_id}/accounts/?offset=400&limit=100",
                },
                "previous": {
                    "type": "string",
                    "nullable": True,
                    "format": "uri",
                    "example": "https://app.posthog.com/api/projects/{project_id}/accounts/?offset=400&limit=100",
                },
                "count": {"type": "integer", "example": 400},
                "results": schema,
            },
        }


def get_person_name(team: Team, person: Person) -> str:
    return get_person_name_helper(person.pk, person.properties, person.distinct_ids, team)


def get_person_name_helper(
    person_pk: int, person_properties: dict[str, str], distinct_ids: list[str], team: Team
) -> str:
    display_name = None
    for property in team.person_display_name_properties or PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES:
        if person_properties and person_properties.get(property):
            display_name = person_properties.get(property)
            break
    if display_name:
        return display_name
    if len(distinct_ids) > 0:
        # Prefer non-UUID distinct IDs (presumably from user identification) over UUIDs
        return sorted(distinct_ids, key=is_anonymous_id)[0]
    return str(person_pk)


class PersonsWebBurstThrottle(UserOrEmailRateThrottle):
    scope = "persons_burst"
    rate = "180/minute"


class PersonsWebSustainedThrottle(UserOrEmailRateThrottle):
    scope = "persons_sustained"
    rate = "1200/hour"


class PersonsDeleteBurstThrottle(PersonalApiKeyRateThrottle):
    scope = "persons_delete_burst"
    rate = "480/minute"


class PersonsDeleteSustainedThrottle(PersonalApiKeyRateThrottle):
    scope = "persons_delete_sustained"
    rate = "4800/hour"


class PersonUpdatePropertyRequestSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="The property key to set.")
    value = serializers.JSONField(help_text="The property value. Can be a string, number, boolean, or object.")


class PersonDeletePropertyRequestSerializer(serializers.Serializer):
    def get_fields(self):
        fields = super().get_fields()
        # The endpoint reads request.data["$unset"], so the field name must include the $ prefix.
        fields["$unset"] = serializers.CharField(help_text="The property key to remove from this person.")
        return fields


class PersonBulkDeleteRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="A list of PostHog person UUIDs to delete (max 1000).",
    )
    distinct_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="A list of distinct IDs whose associated persons will be deleted (max 1000).",
    )
    delete_events = serializers.BooleanField(
        required=False,
        default=False,
        help_text="If true, queue deletion of all events associated with these persons.",
    )
    delete_recordings = serializers.BooleanField(
        required=False,
        default=False,
        help_text="If true, queue deletion of all recordings associated with these persons.",
    )
    keep_person = serializers.BooleanField(
        required=False,
        default=False,
        help_text="If true, keep the person records but delete their events and recordings.",
    )


class PersonBulkDeleteResponseSerializer(serializers.Serializer):
    persons_found = serializers.IntegerField(help_text="Number of persons matched by the provided IDs or distinct IDs.")
    persons_deleted = serializers.IntegerField(
        help_text="Number of person records deleted from the database. 0 if keep_person was true."
    )
    events_queued_for_deletion = serializers.BooleanField(
        help_text="Whether event deletion was requested for the matched persons. "
        "If a deletion was already queued for a person, it will not be duplicated."
    )
    recordings_queued_for_deletion = serializers.BooleanField(
        help_text="Whether recording deletion was requested for the matched persons. "
        "If a deletion was already queued for a person, it will not be duplicated."
    )
    deletion_errors = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text="Persons that could not be deleted. Each entry contains 'person_uuid'. Contact support if this persists.",
    )


class PersonSplitRequestSerializer(serializers.Serializer):
    main_distinct_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text=(
            "The distinct_id to **keep** on this person; every *other* distinct_id is moved "
            "to its own new single-id person. If omitted, the first distinct_id on the person "
            "is kept. The original person always retains its properties; to clear individual "
            "properties afterward, use the delete_property endpoint. "
            "To surgically *remove* one or more distinct_ids while leaving the merge intact, "
            "use `distinct_ids_to_split` instead — these parameters are inverses of each other "
            "and cannot be combined."
        ),
    )
    distinct_ids_to_split = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text=(
            "List of distinct_ids to **move off** this person onto new single-id persons. "
            "The original person keeps every other distinct_id and its properties. New persons "
            "are created with deterministic UUIDs derived from `(team_id, distinct_id)`. "
            "Cannot be combined with `main_distinct_id`."
        ),
    )


class PersonSplitResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(
        help_text=(
            "Always `true` when the split task was enqueued. The split itself runs "
            "asynchronously — a 201 response means the task was accepted, not that the "
            "merge state has already been updated."
        )
    )


class AsyncDeletionStatusSerializer(serializers.Serializer):
    person_uuid = serializers.CharField(
        source="key", help_text="The UUID of the person whose events are queued for deletion."
    )
    created_at = serializers.DateTimeField(help_text="When the deletion was requested.")
    status = serializers.SerializerMethodField(help_text="Current status: 'pending' or 'completed'.")
    delete_verified_at = serializers.DateTimeField(
        help_text="When the deletion was verified complete. Null if still pending.", allow_null=True
    )

    def get_status(self, obj: AsyncDeletion) -> str:
        return "completed" if obj.delete_verified_at else "pending"


class DeletionStatusQueryParamsSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["pending", "completed", "all"],
        default="all",
        required=False,
    )
    person_uuid = serializers.UUIDField(required=False)


class DeletionStatusPagination(LimitOffsetPagination):
    default_limit = 100


@extend_schema_serializer(component_name="PersonRecord")
class PersonSerializer(serializers.HyperlinkedModelSerializer):
    name = serializers.SerializerMethodField(
        help_text="Display name derived from person properties (email, name, or username)."
    )

    class Meta:
        model = Person
        fields = [
            "id",
            "name",
            "distinct_ids",
            "properties",
            "created_at",
            "uuid",
            "last_seen_at",
        ]
        read_only_fields = ("id", "name", "distinct_ids", "created_at", "uuid", "last_seen_at")
        extra_kwargs = {
            "id": {"help_text": "Numeric person ID."},
            "uuid": {"help_text": "Unique identifier (UUID) for this person."},
            "properties": {"help_text": "Key-value map of person properties set via $set and $set_once operations."},
            "created_at": {"help_text": "When this person was first seen (ISO 8601)."},
            "last_seen_at": {"help_text": "Timestamp of the last event from this person, or null."},
        }

    def get_name(self, person: Person) -> str:
        team = self.context["get_team"]()
        return get_person_name(team, person)

    def to_representation(self, instance: Union[Person, MissingPerson]) -> dict[str, Any]:
        if isinstance(instance, Person):
            representation = super().to_representation(instance)
            representation["distinct_ids"] = sorted(representation["distinct_ids"], key=is_anonymous_id)
            restricted = self.context.get("restricted_person_properties")
            if restricted and representation.get("properties"):
                representation["properties"] = {
                    k: v for k, v in representation["properties"].items() if k not in restricted
                }
            return representation
        elif isinstance(instance, MissingPerson):
            return {
                "id": None,
                "name": None,
                "distinct_ids": [instance.distinct_id],
                "properties": instance.properties,
                "created_at": None,
                "uuid": instance.uuid,
                "last_seen_at": None,
            }


# person distinct ids can grow to be a very large list
# in the UI we don't need all of them, so we can limit the number of distinct ids we return
@extend_schema_serializer(component_name="MinimalPerson")
class MinimalPersonSerializer(PersonSerializer):
    distinct_ids = serializers.SerializerMethodField()

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_distinct_ids(self, person):
        return person.distinct_ids[:10]


class PersonPropertiesAtTimeMetadataSerializer(serializers.Serializer):
    """Serializer for the point-in-time query metadata."""

    queried_timestamp = serializers.CharField(help_text="The timestamp that was queried in ISO format")
    include_set_once = serializers.BooleanField(help_text="Whether $set_once operations were included")
    distinct_id_used = serializers.CharField(allow_null=True, help_text="The distinct_id parameter used in the request")
    person_id_used = serializers.CharField(allow_null=True, help_text="The person_id parameter used in the request")
    query_mode = serializers.CharField(help_text="Whether the query used 'distinct_id' or 'person_id' mode")
    distinct_ids_queried = serializers.ListField(
        child=serializers.CharField(), help_text="All distinct_ids that were queried for this person"
    )
    distinct_ids_count = serializers.IntegerField(help_text="Number of distinct_ids associated with this person")


class PersonPropertiesAtTimeResponseSerializer(serializers.Serializer):
    """Serializer for the point-in-time person properties response."""

    # Base PersonSerializer fields
    id = serializers.IntegerField(help_text="The person ID")
    name = serializers.CharField(help_text="The person's display name")
    distinct_ids = serializers.ListField(
        child=serializers.CharField(), help_text="All distinct IDs associated with this person"
    )
    properties = serializers.DictField(
        child=serializers.CharField(allow_blank=True, allow_null=True),
        help_text="Person properties as they existed at the specified time",
    )
    created_at = serializers.DateTimeField(help_text="When the person was first created")
    uuid = serializers.UUIDField(help_text="The person's UUID")
    last_seen_at = serializers.DateTimeField(help_text="When the person was last seen", allow_null=True)

    # Additional fields for point-in-time response
    point_in_time_metadata = PersonPropertiesAtTimeMetadataSerializer(
        help_text="Metadata about the point-in-time query"
    )


_PERSON_ID_PARAMETER = OpenApiParameter(
    "id",
    OpenApiTypes.STR,
    location=OpenApiParameter.PATH,
    description="A unique value identifying this person. Accepts both numeric ID and UUID.",
)

_id_schema = extend_schema(parameters=[_PERSON_ID_PARAMETER])


# Per-action distinct-id fetch caps for the person loaded by ``safely_get_object``. Listed actions
# read only one distinct_id (property updates) or none (``destroy``/``activity`` use the uuid/pk;
# ``properties_timeline``/``delete_events`` don't read distinct_ids), so the fetch is capped here.
# Any action not listed falls back to an unbounded fetch — the same default as the underlying client
# — which is what the full-set actions (``retrieve``, ``split``, ``delete_recordings``) need.
_GET_OBJECT_DISTINCT_ID_LIMITS: dict[str, int] = {
    "destroy": 0,
    "activity": 0,
    "properties_timeline": 0,
    "delete_events": 0,
    "update": 1,
    "partial_update": 1,
    "update_property": 1,
}


@extend_schema(extensions={"x-product": ProductKey.PERSONS})
@extend_schema_view(
    retrieve=_id_schema,
    update=_id_schema,
    partial_update=_id_schema,
    destroy=_id_schema,
)
class PersonViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
    """

    scope_object = "person"
    renderer_classes = cast(
        tuple[type[BaseRenderer], ...],
        (*tuple(api_settings.DEFAULT_RENDERER_CLASSES), csvrenderers.PaginatedCSVRenderer),
    )
    parser_classes = [JSONParser]
    queryset = Person.objects.none()
    serializer_class = PersonSerializer
    pagination_class = PersonLimitOffsetPagination

    def get_throttles(self):
        # API is commonly used for data deletion, so we want to throttle that less aggressively
        if isinstance(self.request.successful_authenticator, PersonalAPIKeyAuthentication):
            if self.action in ("destroy", "bulk_delete", "delete_events", "delete_recordings"):
                return [PersonsDeleteBurstThrottle(), PersonsDeleteSustainedThrottle()]
            else:
                return [ClickHouseBurstRateThrottle()]

        # We have seen issues in the past with the app hammering the API so for app authenticated requests
        # we still want some throttle protection
        return [
            PersonsWebBurstThrottle(),
            PersonsWebSustainedThrottle(),
        ]

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        from posthog.models import PropertyDefinition

        from products.access_control.backend.property_access_control import get_restricted_property_names

        user = self.request.user if self.request.user.is_authenticated else None
        context["restricted_person_properties"] = get_restricted_property_names(
            team_id=self.team_id,
            user=user,
            property_type=PropertyDefinition.Type.PERSON,
        )
        return context

    def safely_get_object(self, queryset):
        person_id = self.kwargs[self.lookup_field]

        try:
            uuid.UUID(str(person_id))
        except ValueError:
            try:
                int(person_id)
            except (ValueError, TypeError):
                raise ValidationError(
                    f"The ID provided does not look like a personID. If you are using a distinctId, please use /persons?distinct_id={person_id} instead."
                )

        with personhog_caller_tag(f"persons/{self.action.replace('_', '-')}"):
            return get_person_by_pk_or_uuid(
                self.team_id, str(person_id), distinct_id_limit=_GET_OBJECT_DISTINCT_ID_LIMITS.get(self.action)
            )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "email",
                OpenApiTypes.STR,
                description="Filter persons by email (exact match)",
                examples=[OpenApiExample(name="email", value="test@test.com")],
            ),
            OpenApiParameter(
                "distinct_id",
                OpenApiTypes.STR,
                description="Filter list by distinct id.",
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Search persons, either by email (full text search) or distinct_id (exact match).",
            ),
            PersonPropertiesSerializer(required=False),
        ],
    )
    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        tag_queries(product=ProductKey.PERSONS, feature=Feature.QUERY)
        team = self.team
        filter = Filter(request=request, team=self.team)

        assert request.user.is_authenticated

        is_csv_request = self.request.accepted_renderer.format == "csv"
        if is_csv_request:
            filter = filter.shallow_clone({LIMIT: CSV_EXPORT_LIMIT, OFFSET: 0})
        elif not filter.limit:
            filter = filter.shallow_clone({LIMIT: DEFAULT_PAGE_LIMIT})

        from posthog.hogql import ast  # noqa: PLC0415 — deferred to avoid a circular import at module load
        from posthog.hogql.query import execute_hogql_query  # noqa: PLC0415

        from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner  # noqa: PLC0415
        from posthog.models.person.util import get_person_by_distinct_id  # noqa: PLC0415

        person_properties: list[dict] = []
        raw_properties = request.GET.get("properties")
        if raw_properties:
            for prop in json.loads(raw_properties):
                # Legacy person filters default to the "exact" operator; ActorsQuery requires it explicitly.
                if prop.get("type") != "cohort":
                    prop.setdefault("operator", "exact")
                person_properties.append(prop)
        if filter.email:
            person_properties.append({"type": "person", "key": "email", "value": filter.email, "operator": "exact"})
        if filter.distinct_id:
            # Exact match on any of the person's distinct IDs; no matching person => no results.
            matched = get_person_by_distinct_id(team.pk, filter.distinct_id)
            person_properties.append({"type": "hogql", "key": f"id = toUUID('{matched.uuid}')" if matched else "1 = 2"})
        actors_query = ActorsQuery(
            select=["id"],
            properties=person_properties,
            search=filter.search or None,
            orderBy=["created_at DESC", "id DESC"],
            limit=filter.limit,
            offset=filter.offset,
        )
        # Use .calculate() (not .run()) — it applies the limit/offset paginator but skips the
        # insight-caching wrapper. With an id-only select there's no actor-column hydration, so
        # we still hydrate the person objects ourselves via get_serialized_people.
        actors_runner = ActorsQueryRunner(team=team, query=actors_query)
        actor_ids = [row[0] for row in actors_runner.calculate().results]
        with personhog_caller_tag("persons/list"):
            serialized_actors = get_serialized_people(team, actor_ids)

        restricted_person_properties = self.get_serializer_context().get("restricted_person_properties")
        if restricted_person_properties:
            for person_dict in serialized_actors:
                properties = person_dict.get("properties")
                if isinstance(properties, dict):
                    person_dict["properties"] = {
                        k: v for k, v in properties.items() if k not in restricted_person_properties
                    }

        _should_paginate = len(actor_ids) >= filter.limit

        # If the undocumented include_total param is set to true, we'll return the total count of people
        # This is extra time and DB load, so we only do this when necessary, which is in PostHog 3000 navigation
        # TODO: Use a more scalable solution before PostHog 3000 navigation is released, and remove this param
        total_count: Optional[int] = None
        if "include_total" in request.GET:
            count_inner = actors_runner.to_query()
            count_inner.limit = None
            count_inner.offset = None
            count_query = ast.SelectQuery(
                select=[ast.Call(name="count", args=[])],
                select_from=ast.JoinExpr(table=count_inner),
            )
            total_count = execute_hogql_query(count_query, team=team).results[0][0]

        next_url = format_query_params_absolute_url(request, filter.offset + filter.limit) if _should_paginate else None
        previous_url = (
            format_query_params_absolute_url(request, filter.offset - filter.limit)
            if filter.offset - filter.limit >= 0
            else None
        )

        # TEMPORARY: Work out usage patterns of this endpoint
        renderer = SafeJSONRenderer()
        size = len(renderer.render(serialized_actors))
        API_PERSON_LIST_BYTES_READ_FROM_POSTGRES_COUNTER.labels(team_id=team.pk).inc(size)

        return Response(
            {
                "results": serialized_actors,
                "next": next_url,
                "previous": previous_url,
                **({"count": total_count} if total_count is not None else {}),
            }
        )

    @extend_schema(
        exclude=True,  # NOTE: We exclude as we want to push people to use the more powerful bulk_delete endpoint
        parameters=[
            OpenApiParameter(
                "delete_events",
                OpenApiTypes.BOOL,
                description="If true, a task to delete all events associated with this person will be created and queued. The task does not run immediately and instead is batched together and at 5AM UTC every Sunday",
                default=False,
            ),
        ],
    )
    def destroy(self, request: request.Request, pk=None, **kwargs):
        """
        Use this endpoint to delete individual persons. For bulk deletion, use the bulk_delete endpoint instead.
        """
        try:
            person = self.get_object()
            # Convert query params to request data format expected by bulk_delete
            self._bulk_delete_persons(
                request=request,
                ids=[str(person.uuid)],
                delete_events="delete_events" in request.GET,
                delete_recordings="delete_recordings" in request.GET,
                keep_person="keep_person" in request.GET,
            )
            return response.Response(status=202)

        except Person.DoesNotExist:
            raise NotFound(detail="Person not found.")

    @extend_schema(
        request=PersonBulkDeleteRequestSerializer,
        responses={202: PersonBulkDeleteResponseSerializer},
    )
    @action(methods=["POST"], detail=False, required_scopes=["person:write"])
    def bulk_delete(self, request: request.Request, pk=None, **kwargs):
        """
        This endpoint allows you to bulk delete persons, either by the PostHog person IDs or by distinct IDs. You can pass in a maximum of 1000 IDs per call. Only events captured before the request will be deleted.
        """

        delete_events = bool(request.data.get("delete_events"))
        delete_recordings = bool(request.data.get("delete_recordings"))
        keep_person = bool(request.data.get("keep_person"))

        summary = self._bulk_delete_persons(
            request=request,
            distinct_ids=request.data.get("distinct_ids"),
            ids=request.data.get("ids"),
            delete_events=delete_events,
            delete_recordings=delete_recordings,
            keep_person=keep_person,
        )

        return response.Response(data=summary, status=202)

    def _bulk_delete_persons(
        self,
        request: request.Request,
        distinct_ids: builtins.list[str] | None = None,
        ids: builtins.list[str] | None = None,
        delete_events: bool = False,
        delete_recordings: bool = False,
        keep_person: bool = False,
    ) -> dict[str, Any]:
        if distinct_ids and ids:
            raise ValidationError("You must provide either distinct_ids or ids, not both")
        if distinct_ids and len(distinct_ids) > 1000:
            raise ValidationError("You can only pass 1000 distinct_ids in one call")
        if ids and len(ids) > 1000:
            raise ValidationError("You can only pass 1000 ids in one call")
        if not distinct_ids and not ids:
            raise ValidationError("You need to specify either distinct_ids or ids")

        persons = resolve_persons_for_deletion(self.team_id, ids, distinct_ids)

        persons_deleted = 0
        errors: builtins.list[dict[str, str]] = []
        if not keep_person:
            result = delete_persons_profile(
                self.team_id,
                persons,
                actor=cast(User, request.user),
                request=request,
                organization_id=self.organization.id,
            )
            persons_deleted = result.deleted_count
            errors = [{"person_uuid": str(u)} for u in result.errors]

        if delete_events:
            queue_person_event_deletion(self.team_id, persons, actor=cast(User, request.user))
        if delete_recordings:
            queue_person_recording_deletion(self.team_id, persons, actor=cast(User, request.user))

        return {
            "persons_found": len(persons),
            "persons_deleted": persons_deleted,
            "events_queued_for_deletion": delete_events and len(persons) > 0,
            "recordings_queued_for_deletion": delete_recordings and len(persons) > 0,
            "deletion_errors": errors,
        }

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                description="Filter by deletion status: 'pending', 'completed', or 'all'.",
                required=False,
                enum=["pending", "completed", "all"],
            ),
            OpenApiParameter(
                "person_uuid",
                OpenApiTypes.UUID,
                description="Filter by a specific person UUID.",
                required=False,
            ),
        ],
        responses={200: AsyncDeletionStatusSerializer(many=True)},
    )
    @action(methods=["GET"], detail=False, required_scopes=["person:read"])
    def deletion_status(self, request: request.Request, **kwargs):
        """
        List the status of queued event deletions for persons. When you delete a person with `delete_events=true`, an async deletion is queued. Use this endpoint to check whether those deletions are still pending or have been completed.
        """
        params = DeletionStatusQueryParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        queryset = AsyncDeletion.objects.filter(
            team_id=self.team_id,
            deletion_type=DeletionType.Person,
        ).order_by("-created_at")

        status_filter = params.validated_data.get("status", "all")
        if status_filter == "pending":
            queryset = queryset.filter(delete_verified_at__isnull=True)
        elif status_filter == "completed":
            queryset = queryset.filter(delete_verified_at__isnull=False)

        person_uuid = params.validated_data.get("person_uuid")
        if person_uuid:
            queryset = queryset.filter(key=str(person_uuid))

        paginator = DeletionStatusPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = AsyncDeletionStatusSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "key",
                OpenApiTypes.STR,
                description="The person property key to get values for (e.g., 'email', 'plan', 'role').",
                required=True,
            ),
            OpenApiParameter(
                "value",
                OpenApiTypes.STR,
                description="Optional search string to filter values (case-insensitive substring match).",
                required=False,
            ),
        ]
    )
    @action(methods=["GET"], detail=False, required_scopes=["person:read"])
    def values(self, request: request.Request, **kwargs) -> response.Response:
        from posthog.hogql_queries.property_values_query_runner import (
            CachedPropertyValuesQueryResponse,
            PropertyType,
            PropertyValuesQuery,
            PropertyValuesQueryResponse,
            PropertyValuesQueryRunner,
        )
        from posthog.hogql_queries.query_runner import ExecutionMode, execution_mode_from_refresh

        tag_queries(product=ProductKey.PERSONS, feature=Feature.QUERY)
        with (
            PROPERTY_VALUES_DURATION.labels(endpoint_type="person").time(),
            tracer.start_as_current_span("person_api_property_values") as span,
        ):
            key = request.GET.get("key")
            value = request.GET.get("value")

            span.set_attribute("team_id", self.team.pk)
            span.set_attribute("property_key", key or "")
            span.set_attribute("has_value_filter", value is not None)

            if not key or key.startswith("$virt"):
                span.set_attribute("result_count", 0)
                resp = response.Response({"results": [], "refreshing": False})
                resp["Cache-Control"] = "max-age=10"
                return resp

            tag_queries(product=ProductKey.PRODUCT_ANALYTICS, feature=Feature.QUERY)
            # Check field-level access control: return empty results for restricted properties
            from posthog.models import PropertyDefinition

            from products.access_control.backend.property_access_control import get_restricted_property_names

            user = request.user if request.user.is_authenticated else None
            restricted = get_restricted_property_names(
                team_id=self.team.pk,
                user=user,
                property_type=PropertyDefinition.Type.PERSON,
            )
            if key in restricted:
                span.set_attribute("result_count", 0)
                resp = response.Response({"results": [], "refreshing": False})
                resp["Cache-Control"] = "max-age=10"
                return resp

            refresh = refresh_requested_by_client(request)
            runner = PropertyValuesQueryRunner(
                team=self.team,
                query=PropertyValuesQuery(
                    property_type=PropertyType.PERSON,
                    property_key=key,
                    search_value=value,
                ),
            )
            execution_mode = execution_mode_from_refresh(refresh)
            if execution_mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE and not refresh:
                execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
            result = runner.run(execution_mode, analytics_props=get_request_analytics_properties(request))
            assert isinstance(result, (PropertyValuesQueryResponse, CachedPropertyValuesQueryResponse))
            is_refreshing = (
                isinstance(result, CachedPropertyValuesQueryResponse)
                and result.query_status is not None
                and not result.query_status.complete
            )
            results = [item.model_dump(exclude_none=True) for item in result.results]
            span.set_attribute("result_count", len(results))
            span.set_attribute("is_refreshing", is_refreshing)
            resp = response.Response({"results": results, "refreshing": is_refreshing})
            resp["Cache-Control"] = "max-age=10"
            return resp

    @extend_schema(
        description=(
            "Split distinct_ids off a merged person. Two mutually exclusive modes:\n\n"
            "- **`distinct_ids_to_split`** (recommended for surgical edits): moves only the "
            "listed distinct_ids off this person onto new single-id persons. The original "
            "person keeps every other distinct_id and its properties.\n"
            "- **`main_distinct_id`**: keeps only the specified distinct_id "
            "on this person; moves every *other* distinct_id off onto its own new person. If "
            "omitted, the first distinct_id is kept.\n\n"
            "The original person always retains its properties. To clear individual "
            "properties afterward, use the `delete_property` endpoint.\n\n"
            "The split runs asynchronously: a 201 response means the task was enqueued. "
            "Newly-created split-off persons get a deterministic UUID derived from "
            "`(team_id, distinct_id)`, so they can be located client-side without polling. "
            "If you need to delete a split-off person after this call, prefer looking it up by "
            "that deterministic UUID rather than by distinct_id, since the latter still "
            "resolves to the original merged person until the async task completes."
        ),
        request=PersonSplitRequestSerializer,
        responses={201: PersonSplitResponseSerializer},
        parameters=[_PERSON_ID_PARAMETER],
    )
    @action(methods=["POST"], detail=True, required_scopes=["person:write"])
    def split(self, request: request.Request, pk=None, **kwargs) -> response.Response:
        person: Person = self.get_object()
        distinct_ids = person.distinct_ids

        main_distinct_id = request.data.get("main_distinct_id")
        distinct_ids_to_split = request.data.get("distinct_ids_to_split")

        if distinct_ids_to_split is not None:
            if not isinstance(distinct_ids_to_split, list) or not all(
                isinstance(did, str) for did in distinct_ids_to_split
            ):
                raise ValidationError({"distinct_ids_to_split": "must be a list of strings"})
            if not distinct_ids_to_split:
                raise ValidationError({"distinct_ids_to_split": "must not be empty"})
            if main_distinct_id is not None:
                raise ValidationError("main_distinct_id cannot be combined with distinct_ids_to_split")
            unknown = set(distinct_ids_to_split) - set(distinct_ids)
            if unknown:
                raise ValidationError({"distinct_ids_to_split": f"not on this person: {sorted(unknown)}"})

        split_person.delay(
            person.id,
            person.team_id,
            main_distinct_id,
            None,
            distinct_ids_to_split=distinct_ids_to_split,
        )

        activity_after: dict = {"distinct_ids": distinct_ids}
        if distinct_ids_to_split is not None:
            activity_after["distinct_ids_to_split"] = list(distinct_ids_to_split)

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
            item_id=person.id,
            scope="Person",
            activity="split_person",
            detail=Detail(
                name=str(person.uuid),
                changes=[
                    Change(
                        type="Person",
                        action="split",
                        after=activity_after,
                    )
                ],
            ),
        )

        return response.Response({"success": True}, status=201)

    @extend_schema(request=PersonUpdatePropertyRequestSerializer, parameters=[_PERSON_ID_PARAMETER])
    @action(methods=["POST"], detail=True, required_scopes=["person:write"])
    def update_property(self, request: request.Request, pk=None, **kwargs) -> response.Response:
        if "value" not in request.data:
            return Response(
                {
                    "attr": "value",
                    "code": "This field is required.",
                    "detail": "required",
                    "type": "validation_error",
                },
                status=400,
            )
        if request.data.get("key") is None:
            return Response(
                {
                    "attr": "key",
                    "code": "This field is required.",
                    "detail": "required",
                    "type": "validation_error",
                },
                status=400,
            )
        key = request.data["key"]
        non_writable = self._get_non_writable_person_properties(request)
        if key in non_writable:
            raise ValidationError(f'You do not have write access to the property "{key}".')
        self._set_properties({key: request.data["value"]}, request.user)
        return Response(status=202)

    @extend_schema(request=PersonDeletePropertyRequestSerializer, parameters=[_PERSON_ID_PARAMETER])
    @action(methods=["POST"], detail=True, required_scopes=["person:write"])
    def delete_property(self, request: request.Request, pk=None, **kwargs) -> response.Response:
        # Only distinct_ids[0] is used (to attribute the property-update event), so bound the fetch to one.
        with personhog_caller_tag("persons/delete-property"):
            person = get_person_by_pk_or_uuid(self.team_id, pk, distinct_id_limit=1)
        if person is None:
            raise Person.DoesNotExist

        key = request.data.get("$unset")
        if key:
            non_writable = self._get_non_writable_person_properties(request)
            if key in non_writable:
                raise ValidationError(f'You do not have write access to the property "{key}".')

        event_name = "$delete_person_property"
        distinct_id = person.distinct_ids[0]
        timestamp = datetime.now(UTC)
        properties = {
            "$unset": [request.data["$unset"]],
        }

        try:
            result = capture_internal(
                token=self.team.api_token,
                event_name=event_name,
                event_source="person_viewset",
                distinct_id=distinct_id,
                timestamp=timestamp,
                properties=properties,
                process_person_profile=True,
            )
            result.raise_for_status()

        except CaptureInternalError as cre:
            logger.warning(
                "delete_person_property.capture_http_error",
                team_id=self.team_id,
                person_uuid=str(person.uuid),
                property_key=request.data.get("$unset"),
                status_code=cre.status_code,
            )
            return response.Response(
                {
                    "success": False,
                    "detail": "Unable to delete property",
                },
                status=cre.status_code or 502,
            )

        except Exception:
            logger.exception(
                "delete_person_property.capture_error",
                team_id=self.team_id,
                person_uuid=str(person.uuid),
                property_key=request.data.get("$unset"),
            )
            return response.Response(
                {
                    "success": False,
                    "detail": "Unable to delete property",
                },
                status=400,
            )

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
            item_id=person.id,
            scope="Person",
            activity="delete_property",
            detail=Detail(name=str(person.uuid), changes=[Change(type="Person", action="changed")]),
        )

        return response.Response({"success": True}, status=201)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "person_id",
                OpenApiTypes.STR,
                description="The person ID or UUID to get cohorts for.",
                required=True,
            ),
        ]
    )
    @action(methods=["GET"], detail=False, required_scopes=["person:read", "cohort:read"])
    def cohorts(self, request: request.Request, **kwargs) -> response.Response:
        from posthog.api.cohort import CohortMinimalSerializer

        team = cast(User, request.user).team
        if not team:
            return response.Response(
                {
                    "message": "Could not retrieve team",
                    "detail": "Could not validate team associated with user",
                },
                status=400,
            )

        # Only person.uuid is used below, so skip the distinct-id fetch entirely.
        with personhog_caller_tag("persons/cohorts"):
            person = get_person_by_pk_or_uuid(self.team_id, request.GET["person_id"], distinct_id_limit=0)
        if person is None:
            raise NotFound()
        cohort_ids = get_all_cohort_ids_by_person_uuid(str(person.uuid), team.pk)

        # nosemgrep: idor-lookup-without-team, idor-taint-user-input-to-model-get (IDs from team-scoped ClickHouse query)
        cohorts = Cohort.objects.filter(pk__in=cohort_ids, deleted=False)

        return response.Response({"results": CohortMinimalSerializer(cohorts, many=True).data})

    @extend_schema(operation_id="persons_all_activity_retrieve")
    @action(methods=["GET"], url_path="activity", detail=False, required_scopes=["activity_log:read"])
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="Person", team_id=self.team_id, limit=limit, page=page)
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: request.Request, pk=None, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))
        item_id = None
        if pk:
            person = self.get_object()
            item_id = person.pk

        activity_page = load_activity(
            scope="Person",
            team_id=self.team_id,
            item_ids=[item_id] if item_id else None,
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)

    def update(self, request, *args, **kwargs):
        """
        Only for setting properties on the person. "properties" from the request data will be updated via a "$set" event.
        This means that only the properties listed will be updated, but other properties won't be removed nor updated.
        If you would like to remove a property use the `delete_property` endpoint.
        """
        if request.data.get("properties") is None:
            return Response(
                {
                    "attr": "properties",
                    "code": "This field is required.",
                    "detail": "required",
                    "type": "validation_error",
                },
                status=400,
            )
        non_writable = self._get_non_writable_person_properties(request)
        if non_writable:
            blocked_keys = set(request.data["properties"].keys()) & non_writable
            if blocked_keys:
                raise ValidationError(
                    f"You do not have write access to the following properties: {', '.join(sorted(blocked_keys))}."
                )
        self._set_properties(request.data["properties"], request.user)
        return Response(status=202)

    @extend_schema(exclude=True)
    def create(self, *args, **kwargs):
        raise MethodNotAllowed(
            method="POST",
            detail="Creating persons via this API is not allowed. Please create persons by sending an $identify event. See https://posthog.com/docs/product-analytics/identify for details.",
        )

    def _get_non_writable_person_properties(self, request: request.Request) -> set[str]:
        from posthog.models import PropertyDefinition

        from products.access_control.backend.property_access_control import get_non_writable_property_names

        user = request.user if request.user.is_authenticated else None
        return get_non_writable_property_names(
            team_id=self.team_id,
            user=user,
            property_type=PropertyDefinition.Type.PERSON,
        )

    def _set_properties(self, properties, user):
        instance = self.get_object()
        distinct_id = instance.distinct_ids[0]
        event_name = "$set"
        timestamp = datetime.now(UTC)
        properties = {
            "$set": properties,
        }

        try:
            result = capture_internal(
                token=self.team.api_token,
                event_name=event_name,
                event_source="person_viewset",
                distinct_id=distinct_id,
                timestamp=timestamp,
                properties=properties,
                process_person_profile=True,
            )
            result.raise_for_status()

        # Failures in this codepath are ignored
        except Exception:
            pass

        if self.organization.id:  # should always be true, but mypy...
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team.id,
                user=user,
                was_impersonated=is_impersonated(self.request),
                item_id=instance.pk,
                scope="Person",
                activity="updated",
                detail=Detail(changes=[Change(type="Person", action="changed", field="properties")]),
            )

    # PRAGMA: Methods for getting Persons via clickhouse queries
    def _respond_with_cached_results(
        self, results_package: dict[str, tuple[builtins.list, Optional[str], Optional[str], int]]
    ):  # noqa: UP006
        if not results_package:
            return response.Response(data=[])

        actors, next_url, initial_url, missing_persons = results_package["result"]

        return response.Response(
            data={
                "results": [{"people": actors, "count": len(actors)}],
                "next": next_url,
                "initial": initial_url,
                "missing_persons": missing_persons,
                "is_cached": results_package.get("is_cached"),
                "last_refresh": results_package.get("last_refresh"),
            }
        )

    def _legacy_session_ids_with_recordings(self, session_ids: set[str], filter: Filter) -> set[str]:
        """Filter session ids to those with a (non-deleted) recording, mirroring the legacy actor endpoint.
        Unlike the modern RecordingsHelper this does not apply a retention/expiry window, preserving the
        long-standing response shape of these public endpoints.
        """
        if not session_ids:
            return set()

        from posthog.clickhouse.client import sync_execute  # noqa: PLC0415

        query = """
            SELECT session_id
            FROM session_replay_events
            WHERE team_id = %(team_id)s AND session_id IN %(session_ids)s
        """
        params: dict[str, Any] = {"team_id": self.team.pk, "session_ids": sorted(session_ids)}
        if filter.date_from:
            query += " AND min_first_timestamp >= %(date_from)s"
            params["date_from"] = filter.date_from - timedelta(days=1)
        if filter.date_to:
            query += " AND max_last_timestamp <= %(date_to)s"
            params["date_to"] = filter.date_to + timedelta(days=1)
        query += " GROUP BY session_id HAVING max(is_deleted) = 0"

        return {row[0] for row in sync_execute(query, params)}

    @staticmethod
    def _legacy_breakdown_value(filter: Filter) -> Optional[Union[str, int]]:
        """Translate the legacy `breakdown_value` request param into the value the HogQL trends actors path
        expects: an empty string means the null/none bucket, a cohort breakdown value is an int cohort id.
        """
        from posthog.hogql_queries.insights.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL  # noqa: PLC0415

        value = filter.breakdown_value
        if value is None:
            return None
        if filter.breakdown_type == "cohort":
            return value if value == "all" else int(value)
        if value == "":
            return BREAKDOWN_NULL_STRING_LABEL
        return value

    def _run_legacy_actors_query(
        self,
        source: Any,
        filter: Filter,
        *,
        aggregation_group_type_index: Optional[int],
        include_value: bool,
        include_recordings: bool,
    ) -> tuple[builtins.list, int]:
        """Run an ActorsQuery (the HogQL actor path used by the modern /query route) and reshape the
        results into the legacy SerializedPerson/SerializedGroup envelope these endpoints have always
        returned. `source` is an InsightActorsQuery or FunnelsActorsQuery.
        """
        from posthog.schema import HogQLQueryModifiers, InlineCohortCalculation  # noqa: PLC0415

        from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner  # noqa: PLC0415
        from posthog.queries.actor_base_query import get_groups  # noqa: PLC0415

        # Raw id-only select (plus value/recordings columns) — we hydrate actors ourselves below, matching
        # the legacy SerializedPerson shape rather than the ActorsQuery strategy dict.
        select: list[str] = ["actor_id"]
        if include_value:
            select.append("event_count")
        if include_recordings:
            select.append("matched_recordings")

        actors_query = ActorsQuery(
            source=source,
            select=select,
            limit=filter.limit,
            offset=filter.offset,
        )
        # Inline cohort definitions instead of reading precomputed membership — the legacy actor queries
        # expanded cohorts inline, so a cohort breakdown/filter works without a prior cohort calculation.
        # The modifiers must live on the inner insight query: ActorsQueryRunner inherits its modifiers from
        # the source query runner, which derives them from `source.source.modifiers`.
        source.source.modifiers = (source.source.modifiers or HogQLQueryModifiers()).model_copy(
            update={"inlineCohortCalculation": InlineCohortCalculation.ALWAYS}
        )
        runner = ActorsQueryRunner(team=self.team, query=actors_query)
        results = list(runner.calculate().results)
        raw_count = len(results)

        actor_ids = [str(row[0]) for row in results]
        value_per_actor_id: Optional[dict[str, float]] = (
            {str(row[0]): row[1] for row in results} if include_value else None
        )

        serialized_actors: list[Any]
        if aggregation_group_type_index is not None:
            _, serialized_actors = get_groups(self.team.pk, aggregation_group_type_index, actor_ids, value_per_actor_id)
        else:
            serialized_actors = get_serialized_people(self.team, actor_ids, value_per_actor_id)

        if include_recordings:
            recordings_column_index = select.index("matched_recordings")
            all_session_ids = {event[2] for row in results for event in row[recordings_column_index] if event[2]}
            valid_session_ids = self._legacy_session_ids_with_recordings(all_session_ids, filter)
            recordings_by_actor_id: dict[str, builtins.list] = {}
            for row in results:
                events_by_session: dict[str, builtins.list] = {}
                for event in row[recordings_column_index]:
                    session_id = event[2]
                    if session_id and session_id in valid_session_ids:
                        events_by_session.setdefault(session_id, []).append(
                            {"timestamp": event[0], "uuid": event[1], "window_id": event[3]}
                        )
                recordings_by_actor_id[str(row[0])] = [
                    {"session_id": session_id, "events": events} for session_id, events in events_by_session.items()
                ]
            for actor in serialized_actors:
                actor["matched_recordings"] = recordings_by_actor_id.get(str(actor["id"]), [])

        if include_value:
            # get_serialized_people / get_groups fetch actors out of order, so restore the
            # descending-by-value ordering the legacy endpoint guaranteed.
            serialized_actors.sort(key=lambda actor: cast(float, actor["value_at_data_point"]), reverse=True)

        return serialized_actors, raw_count

    @action(methods=["GET", "POST"], detail=False)
    def funnel(self, request: request.Request, **kwargs) -> response.Response:
        capture_legacy_api_call(request, self.team)

        if request.user.is_anonymous or not self.team:
            return response.Response(data=[])

        return self._respond_with_cached_results(self.calculate_funnel_persons(request))

    @cached_by_filters
    def calculate_funnel_persons(
        self, request: request.Request
    ) -> dict[str, tuple[List, Optional[str], Optional[str], int]]:  # noqa: UP006
        from posthog.schema import FunnelsActorsQuery, FunnelsQuery  # noqa: PLC0415

        from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query  # noqa: PLC0415

        filter = Filter(request=request, data={"insight": INSIGHT_FUNNELS}, team=self.team)
        filter = prepare_actor_query_filter(filter)

        funnels_query = cast(FunnelsQuery, filter_to_query(filter.to_dict()))
        if filter.funnel_viz_type == FunnelVizType.TRENDS:
            # Funnel-trends actors are addressed by an entrance period + converted/dropped-off flag,
            # not by a step index.
            source = FunnelsActorsQuery(
                source=funnels_query,
                funnelTrendsDropOff=bool(filter.drop_off),
                funnelTrendsEntrancePeriodStart=request.GET.get("entrance_period_start"),
                funnelStepBreakdown=filter.funnel_step_breakdown,
                includeRecordings=filter.include_recordings,
            )
        else:
            funnel_step = filter.funnel_step
            if funnel_step is None and filter.funnel_custom_steps:
                funnel_step = filter.funnel_custom_steps[0]
            source = FunnelsActorsQuery(
                source=funnels_query,
                funnelStep=funnel_step,
                funnelStepBreakdown=filter.funnel_step_breakdown,
                includeRecordings=filter.include_recordings,
            )

        serialized_actors, raw_count = self._run_legacy_actors_query(
            source,
            filter,
            aggregation_group_type_index=funnels_query.aggregation_group_type_index,
            include_value=False,
            include_recordings=bool(filter.include_recordings),
        )
        initial_url = format_query_params_absolute_url(request, 0)
        next_url = paginated_result(request, raw_count, filter.offset, filter.limit)

        # cached_function expects a dict with the key result
        return {
            "result": (
                serialized_actors,
                next_url,
                initial_url,
                raw_count - len(serialized_actors),
            )
        }

    @action(methods=["GET"], detail=False)
    def trends(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        capture_legacy_api_call(request, self.team)

        if request.user.is_anonymous or not self.team:
            return response.Response(data=[])

        return self._respond_with_cached_results(self.calculate_trends_persons(request))

    @cached_by_filters
    def calculate_trends_persons(
        self, request: request.Request
    ) -> dict[str, tuple[List, Optional[str], Optional[str], int]]:  # noqa: UP006
        from posthog.schema import ChartDisplayType, InsightActorsQuery, TrendsFilter, TrendsQuery  # noqa: PLC0415

        from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query  # noqa: PLC0415

        filter = Filter(request=request, team=self.team)
        filter = prepare_actor_query_filter(filter)
        entity = get_target_entity(filter)

        # The trends person endpoint identifies its target series via the entity params (entity_id/type),
        # not an events/actions list, so inject the resolved entity as the single series before converting.
        filter_dict = {**filter.to_dict(), "insight": "TRENDS"}
        entity_dict = {**entity.to_dict(), "order": 0}
        if entity.type == "actions":
            filter_dict["actions"] = [entity_dict]
            filter_dict["events"] = []
        else:
            filter_dict["events"] = [entity_dict]
            filter_dict["actions"] = []

        trends_query = cast(TrendsQuery, filter_to_query(filter_dict))
        # The legacy endpoint returns every actor that performed the series anywhere in the filter's date
        # range (no per-interval `day`). A total-value display gives exactly that aggregation, so the actors
        # builder doesn't require a `day`.
        trends_query.trendsFilter = trends_query.trendsFilter or TrendsFilter()
        trends_query.trendsFilter.display = ChartDisplayType.ACTIONS_BAR_VALUE
        source = InsightActorsQuery(
            source=trends_query,
            series=0,
            breakdown=self._legacy_breakdown_value(filter),
            includeRecordings=filter.include_recordings,
        )

        serialized_actors, raw_count = self._run_legacy_actors_query(
            source,
            filter,
            aggregation_group_type_index=entity.math_group_type_index,
            include_value=True,
            include_recordings=bool(filter.include_recordings),
        )
        next_url = paginated_result(request, raw_count, filter.offset, filter.limit)
        initial_url = format_query_params_absolute_url(request, 0)

        # cached_function expects a dict with the key result
        return {
            "result": (
                serialized_actors,
                next_url,
                initial_url,
                raw_count - len(serialized_actors),
            )
        }

    @action(methods=["GET"], detail=True)
    def properties_timeline(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        if request.user.is_anonymous or not self.team:
            return response.Response(data=[])

        person = self.get_object()
        filter = PropertiesTimelineFilter(request=request, team=self.team)

        properties_timeline = PropertiesTimeline().run(filter, self.team, person)

        return response.Response(data=properties_timeline)

    @extend_schema(
        parameters=[PersonMessageAssetsRequestSerializer],
        responses=MessageAssetSerializer(many=True),
    )
    @action(methods=["GET"], detail=True, required_scopes=["person:read"])
    def emails(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        person = self.get_object()
        if not workflow_email_assets_ui_enabled(self.team, request.user):
            raise NotFound()
        param_serializer = PersonMessageAssetsRequestSerializer(data=request.query_params)
        param_serializer.is_valid(raise_exception=True)
        params = param_serializer.validated_data

        tag_queries(product=ProductKey.PERSONS, feature=Feature.QUERY)

        after_date, _, _ = relative_date_parse_with_delta_mapping(params["after"], self.team.timezone_info)
        before_date = None
        if params.get("before"):
            before_date, _, _ = relative_date_parse_with_delta_mapping(params["before"], self.team.timezone_info)

        data = fetch_message_assets_for_person(
            team_id=self.team_id,
            person_id=str(person.uuid),
            limit=params["limit"],
            offset=params["offset"],
            after=after_date,
            before=before_date,
        )
        return response.Response(MessageAssetSerializer(data, many=True).data)

    @action(methods=["GET"], detail=False)
    def lifecycle(self, request: request.Request) -> response.Response:
        team = cast(User, request.user).team
        if not team:
            return response.Response(
                {
                    "message": "Could not retrieve team",
                    "detail": "Could not validate team associated with user",
                },
                status=400,
            )

        target_date = request.GET.get("target_date", None)
        if target_date is None:
            return response.Response(
                {
                    "message": "Missing parameter",
                    "detail": "Must include specified date",
                },
                status=400,
            )
        lifecycle_type = request.GET.get("lifecycle_type", None)
        if lifecycle_type is None:
            return response.Response(
                {
                    "message": "Missing parameter",
                    "detail": "Must include lifecycle type",
                },
                status=400,
            )

        from posthog.schema import InsightActorsQuery, LifecycleQuery  # noqa: PLC0415

        from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query  # noqa: PLC0415

        filter = LifecycleFilter(request=request, data=request.GET.dict(), team=self.team)
        filter = prepare_actor_query_filter(filter)

        lifecycle_query = cast(LifecycleQuery, filter_to_query({**filter.to_dict(), "insight": "LIFECYCLE"}))
        source = InsightActorsQuery(source=lifecycle_query, day=target_date, status=lifecycle_type)

        with personhog_caller_tag("persons/lifecycle"):
            people, raw_count = self._run_legacy_actors_query(
                source,
                filter,
                aggregation_group_type_index=lifecycle_query.aggregation_group_type_index,
                include_value=False,
                include_recordings=False,
            )
        next_url = paginated_result(request, raw_count, filter.offset, filter.limit)
        return response.Response({"results": [{"people": people, "count": len(people)}], "next": next_url})

    @extend_schema(
        exclude=True,  # NOTE: We exclude as we want to push people to use the more powerful bulk_delete endpoint
        description="Queue deletion of all recordings associated with this person.",
    )
    @action(methods=["POST"], detail=True, required_scopes=["person:write"])
    def delete_recordings(self, request: request.Request, pk=None, **kwargs) -> response.Response:
        """
        [DEPRECATED] Queue deletion of all recordings for a person without deleting the person record itself.
        """
        try:
            person = self.get_object()
            queue_person_recording_deletion(self.team_id, [person], actor=cast(User, request.user))
            return response.Response(status=202)
        except Person.DoesNotExist:
            raise NotFound(detail="Person not found.")

    @extend_schema(
        exclude=True,  # NOTE: We exclude as we want to push people to use the more powerful bulk_delete endpoint
        description="Queue deletion of all events associated with this person. The task runs during non-peak hours.",
    )
    @action(methods=["POST"], detail=True, required_scopes=["person:write"])
    def delete_events(self, request: request.Request, pk=None, **kwargs) -> response.Response:
        """
        [DEPRECATED] Queue deletion of all events for a person without deleting the person record itself.
        The deletion task runs during non-peak hours.
        """
        try:
            person = self.get_object()
            queue_person_event_deletion(self.team_id, [person], actor=cast(User, request.user))
            return response.Response(status=202)
        except Person.DoesNotExist:
            raise NotFound(detail="Person not found.")

    @extend_schema(
        description="Reset a distinct_id for a deleted person. This allows the distinct_id to be used again.",
    )
    @action(methods=["POST"], detail=False, required_scopes=["person:write"])
    def reset_person_distinct_id(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        distinct_id = request.data.get("distinct_id")
        if not distinct_id or not isinstance(distinct_id, str):
            raise ValidationError(detail="distinct_id is required")

        reset_deleted_person_distinct_ids(self.team_id, distinct_id)

        return response.Response(status=202)

    @action(methods=["POST"], detail=False, url_path="batch_by_distinct_ids", required_scopes=["person:read"])
    def batch_by_distinct_ids(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        distinct_ids = request.data.get("distinct_ids", [])

        if not isinstance(distinct_ids, list) or len(distinct_ids) == 0:
            return response.Response({"results": {}})

        MAX_BATCH_SIZE = 200
        distinct_ids = distinct_ids[:MAX_BATCH_SIZE]

        with personhog_caller_tag("persons/batch-by-distinct-ids"):
            persons_by_distinct_id = get_persons_mapped_by_distinct_id(self.team_id, distinct_ids)

        # The mapped lookup carries only the matched distinct_id; fetch up to 10
        # per person with a bounded follow-up for display, rather than the
        # unbounded fetch get_persons_by_distinct_ids would do. A person may appear
        # under several requested ids, so update every copy.
        persons_by_id: dict[int, list[Person]] = {}
        for person in persons_by_distinct_id.values():
            persons_by_id.setdefault(person.id, []).append(person)
        if persons_by_id:
            with personhog_caller_tag("persons/batch-by-distinct-ids"):
                distinct_ids_by_person = get_distinct_ids_for_persons(
                    self.team_id, list(persons_by_id.keys()), limit_per_person=10
                )
            for person_id, persons in persons_by_id.items():
                ids = distinct_ids_by_person.get(person_id)
                if ids is not None:
                    for person in persons:
                        person._distinct_ids = ids

        serializer_context = {**self.get_serializer_context(), "get_team": lambda: self.team}
        results: dict[str, Any] = {
            distinct_id: MinimalPersonSerializer(person, context=serializer_context).data
            for distinct_id, person in persons_by_distinct_id.items()
        }
        return response.Response({"results": results})

    @action(methods=["POST"], detail=False, url_path="batch_by_uuids", required_scopes=["person:read"])
    def batch_by_uuids(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        uuids = request.data.get("uuids", [])

        if not isinstance(uuids, list) or len(uuids) == 0:
            return response.Response({"results": {}})

        MAX_BATCH_SIZE = 200
        uuids = uuids[:MAX_BATCH_SIZE]

        try:
            uuids = [str(uuid.UUID(u)) for u in uuids]
        except (ValueError, AttributeError):
            raise ValidationError("One or more UUIDs are invalid.")

        # MinimalPersonSerializer only renders 10 distinct_ids, so bound the fetch to match.
        with personhog_caller_tag("persons/batch-by-uuids"):
            persons = get_persons_by_uuids(self.team_id, uuids, distinct_id_limit=10)

        serializer_context = {**self.get_serializer_context(), "get_team": lambda: self.team}
        results: dict[str, Any] = {}
        for person in persons:
            results[str(person.uuid)] = MinimalPersonSerializer(person, context=serializer_context).data

        return response.Response({"results": results})

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="distinct_id",
                type=str,
                location=OpenApiParameter.QUERY,
                description="The distinct_id of the person (mutually exclusive with person_id)",
                required=False,
            ),
            OpenApiParameter(
                name="person_id",
                type=str,
                location=OpenApiParameter.QUERY,
                description="The person_id (UUID) to build properties for (mutually exclusive with distinct_id)",
                required=False,
            ),
            OpenApiParameter(
                name="timestamp",
                type=str,
                location=OpenApiParameter.QUERY,
                description="ISO datetime string for the point in time (e.g., '2023-06-15T14:30:00Z')",
                required=True,
            ),
            OpenApiParameter(
                name="include_set_once",
                type=bool,
                location=OpenApiParameter.QUERY,
                description="Whether to handle $set_once operations (default: false)",
                required=False,
            ),
        ],
        responses={
            200: PersonPropertiesAtTimeResponseSerializer,
            400: {"description": "Bad request - invalid parameters"},
            404: {"description": "Person not found"},
            500: {"description": "Internal server error"},
        },
        tags=["persons"],
    )
    @action(methods=["GET"], detail=False, required_scopes=["person:read"])
    def properties_at_time(self, request: request.Request) -> response.Response:
        """
        Get person properties as they existed at a specific point in time.

        This endpoint reconstructs person properties by querying ClickHouse events
        for $set and $set_once operations up to the specified timestamp.

        Query parameters:
        - distinct_id: The distinct_id of the person
        - timestamp: ISO datetime string for the point in time (e.g., "2023-06-15T14:30:00Z")
        - include_set_once: Whether to handle $set_once operations (default: false)
        """
        from posthog.models.person.point_in_time_properties import (
            build_person_properties_at_time,
            get_person_and_distinct_ids_for_identifier,
        )

        distinct_id = request.GET.get("distinct_id")
        person_id = request.GET.get("person_id")
        timestamp_str = request.GET.get("timestamp")
        include_set_once = request.GET.get("include_set_once", "false").lower() == "true"

        # Validate parameters
        if distinct_id and person_id:
            return response.Response(
                {"error": "Cannot provide both distinct_id and person_id - choose one"},
                status=400,
            )

        if not distinct_id and not person_id:
            return response.Response(
                {"error": "Must provide either distinct_id or person_id parameter"},
                status=400,
            )

        if not timestamp_str:
            return response.Response(
                {"error": "timestamp parameter is required (ISO format: 2023-06-15T14:30:00Z)"},
                status=400,
            )

        try:
            # Parse timestamp - support both with and without timezone
            if timestamp_str.endswith("Z"):
                timestamp = datetime.fromisoformat(timestamp_str[:-1]).replace(tzinfo=UTC)
            elif "+" in timestamp_str or timestamp_str.count("-") > 2:
                timestamp = datetime.fromisoformat(timestamp_str)
            else:
                timestamp = datetime.fromisoformat(timestamp_str).replace(tzinfo=UTC)
        except ValueError as e:
            identifier = distinct_id or person_id
            logger.warning(
                "Invalid timestamp format for %s %s: %s", "distinct_id" if distinct_id else "person_id", identifier, e
            )
            return response.Response(
                {"error": "Invalid timestamp format. Use ISO format like 2023-06-15T14:30:00Z"},
                status=400,
            )

        try:
            # Get person object and all distinct_ids in a single query
            person, distinct_ids_queried = get_person_and_distinct_ids_for_identifier(
                team_id=self.team_id,
                distinct_id=distinct_id,
                person_id=person_id,
            )

            if not person or not distinct_ids_queried:
                identifier = distinct_id or person_id
                identifier_type = "distinct_id" if distinct_id else "person_id"
                return response.Response(
                    {"error": f"Person with {identifier_type} '{identifier}' not found"},
                    status=404,
                )

            # Build point-in-time properties using the pre-fetched distinct_ids
            tag_queries(product=ProductKey.PERSONS, feature=Feature.QUERY, team_id=self.team_id)
            point_in_time_properties = build_person_properties_at_time(
                team_id=self.team_id,
                timestamp=timestamp,
                distinct_ids=distinct_ids_queried,
                include_set_once=include_set_once,
            )

            # Serialize the person object
            person_data = PersonSerializer(person, context={"get_team": lambda: self.team}).data

            # Replace current properties with point-in-time properties
            person_data["properties"] = point_in_time_properties

            # Add metadata about the point-in-time query
            person_data["point_in_time_metadata"] = {
                "queried_timestamp": timestamp.isoformat(),
                "include_set_once": include_set_once,
                "distinct_id_used": distinct_id,
                "person_id_used": person_id,
                "query_mode": "distinct_id" if distinct_id else "person_id",
                "distinct_ids_queried": distinct_ids_queried,
                "distinct_ids_count": len(distinct_ids_queried),
            }

            return response.Response(person_data)

        except Exception:
            identifier = distinct_id or person_id
            identifier_type = "distinct_id" if distinct_id else "person_id"
            logger.exception(
                "Failed to build person properties at time for %s %s",
                identifier_type,
                identifier,
                distinct_id=distinct_id,
                person_id=person_id,
                timestamp=timestamp_str,
            )
            return response.Response(
                {"error": f"Failed to retrieve person properties for {identifier_type} '{identifier}'"},
                status=500,
            )


def paginated_result(
    request: request.Request,
    count: int,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> Optional[str]:
    return format_paginated_url(request, offset, limit) if count >= limit else None


T = TypeVar("T", Filter, PathFilter, RetentionFilter, LifecycleFilter)


def prepare_actor_query_filter(filter: T) -> T:
    if not filter.limit:
        filter = filter.shallow_clone({LIMIT: DEFAULT_PAGE_LIMIT})

    search = getattr(filter, "search", None)
    if not search:
        return filter

    group_properties_filter_group: list[dict[str, object]] = []
    if hasattr(filter, "aggregation_group_type_index"):
        group_properties_filter_group += [
            {
                "key": "name",
                "value": search,
                "type": "group",
                "group_type_index": filter.aggregation_group_type_index,
                "operator": "icontains",
            },
            {
                "key": "slug",
                "value": search,
                "type": "group",
                "group_type_index": filter.aggregation_group_type_index,
                "operator": "icontains",
            },
        ]

    new_group = {
        "type": "OR",
        "values": [
            {"key": "email", "type": "person", "value": search, "operator": "icontains"},
            {"key": "name", "type": "person", "value": search, "operator": "icontains"},
            {"key": "distinct_id", "type": "event", "value": search, "operator": "icontains"},
            *group_properties_filter_group,
        ],
    }
    prop_group = (
        {"type": "AND", "values": [new_group, filter.property_groups.to_dict()]}
        if filter.property_groups.to_dict()
        else new_group
    )

    return filter.shallow_clone({"properties": prop_group, "search": None})


class LegacyPersonViewSet(PersonViewSet):
    param_derived_from_user_current_team = "team_id"
