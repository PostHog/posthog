import json
import posthoganalytics
from posthog.renderers import SafeJSONRenderer
from datetime import datetime
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    cast,
)

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, NotFound, ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers
from statshog.defaults.django import statsd

from posthog.api.capture import capture_internal
from posthog.api.documentation import PersonPropertiesSerializer, extend_schema
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.utils import format_paginated_url, get_pk_or_uuid, get_target_entity
from posthog.constants import (
    CSV_EXPORT_LIMIT,
    INSIGHT_FUNNELS,
    INSIGHT_PATHS,
    LIMIT,
    OFFSET,
    FunnelVizType,
)
from posthog.decorators import cached_by_filters
from posthog.logging.timing import timed
from posthog.models import Cohort, Filter, Person, User, Team
from posthog.models.activity_logging.activity_log import (
    Change,
    Detail,
    load_activity,
    log_activity,
)
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.cohort.util import get_all_cohort_ids_by_person_uuid
from posthog.models.filters.lifecycle_filter import LifecycleFilter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.person.util import delete_person
from posthog.permissions import (
    ProjectMembershipNecessaryPermissions,
    TeamMemberAccessPermission,
)
from posthog.queries.actor_base_query import (
    ActorBaseQuery,
    get_people,
    serialize_people,
)
from posthog.queries.funnels import ClickhouseFunnelActors, ClickhouseFunnelTrendsActors
from posthog.queries.funnels.funnel_strict_persons import ClickhouseFunnelStrictActors
from posthog.queries.funnels.funnel_unordered_persons import (
    ClickhouseFunnelUnorderedActors,
)
from posthog.queries.insight import insight_sync_execute
from posthog.queries.paths import PathsActors
from posthog.queries.person_query import PersonQuery
from posthog.queries.properties_timeline import PropertiesTimeline
from posthog.queries.property_values import get_person_property_values_for_key
from posthog.queries.retention import Retention
from posthog.queries.stickiness import Stickiness
from posthog.queries.trends.lifecycle import Lifecycle
from posthog.queries.trends.trends_actors import TrendsActors
from posthog.queries.util import get_earliest_timestamp
from posthog.rate_limit import (
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
)
from posthog.settings import EE_AVAILABLE
from posthog.tasks.split_person import split_person
from posthog.utils import (
    convert_property_value,
    format_query_params_absolute_url,
    is_anonymous_id,
)
from prometheus_client import Counter
from posthog.metrics import LABEL_TEAM_ID

DEFAULT_PAGE_LIMIT = 100
# Sync with .../lib/constants.tsx and .../ingestion/hooks.ts
PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES = [
    "email",
    "Email",
    "name",
    "Name",
    "username",
    "Username",
    "UserName",
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
    if display_name := get_person_display_name(person, team):
        return display_name
    if len(person.distinct_ids) > 0:
        # Prefer non-UUID distinct IDs (presumably from user identification) over UUIDs
        return sorted(person.distinct_ids, key=is_anonymous_id)[0]
    return person.pk


def get_person_display_name(person: Person, team: Team) -> str | None:
    for property in team.person_display_name_properties or PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES:
        if person.properties and person.properties.get(property):
            return person.properties.get(property)
    return None


class PersonsThrottle(ClickHouseSustainedRateThrottle):
    # Throttle class that's scoped just to the person endpoint.
    # This makes the rate limit apply to all endpoints under /api/person/
    # and independent of other endpoints.
    scope = "persons"


class PersonSerializer(serializers.HyperlinkedModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = [
            "id",
            "name",
            "distinct_ids",
            "properties",
            "created_at",
            "uuid",
        ]
        read_only_fields = ("id", "name", "distinct_ids", "created_at", "uuid")

    def get_name(self, person: Person) -> str:
        team = self.context["get_team"]()
        return get_person_name(team, person)

    def to_representation(self, instance: Person) -> Dict[str, Any]:
        representation = super().to_representation(instance)
        representation["distinct_ids"] = sorted(representation["distinct_ids"], key=is_anonymous_id)
        return representation


def get_funnel_actor_class(filter: Filter) -> Callable:
    funnel_actor_class: Type[ActorBaseQuery]

    if filter.correlation_person_entity and EE_AVAILABLE:
        if EE_AVAILABLE:
            from ee.clickhouse.queries.funnels.funnel_correlation_persons import (
                FunnelCorrelationActors,
            )

            funnel_actor_class = FunnelCorrelationActors
        else:
            raise ValueError(
                "Funnel Correlations is not available without an enterprise license and enterprise supported deployment"
            )
    elif filter.funnel_viz_type == FunnelVizType.TRENDS:
        funnel_actor_class = ClickhouseFunnelTrendsActors
    else:
        if filter.funnel_order_type == "unordered":
            funnel_actor_class = ClickhouseFunnelUnorderedActors
        elif filter.funnel_order_type == "strict":
            funnel_actor_class = ClickhouseFunnelStrictActors
        else:
            funnel_actor_class = ClickhouseFunnelActors

    return funnel_actor_class


class PersonViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    To create or update persons, use a PostHog library of your choice and [use an identify call](/docs/integrate/identifying-users). This API endpoint is only for reading and deleting.
    """

    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (csvrenderers.PaginatedCSVRenderer,)
    queryset = Person.objects.all()
    serializer_class = PersonSerializer
    pagination_class = PersonLimitOffsetPagination
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
    ]
    throttle_classes = [ClickHouseBurstRateThrottle, PersonsThrottle]
    lifecycle_class = Lifecycle
    retention_class = Retention
    stickiness_class = Stickiness

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
        queryset = queryset.only("id", "created_at", "properties", "uuid", "is_identified")
        return queryset

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        person_id = self.kwargs[self.lookup_field]

        try:
            queryset = get_pk_or_uuid(queryset, person_id)
        except ValueError:
            raise ValidationError(
                f"The ID provided does not look like a personID. If you are using a distinctId, please use /persons?distinct_id={person_id} instead."
            )

        obj = get_object_or_404(queryset)

        # May raise a permission denied
        self.check_object_permissions(self.request, obj)

        return obj

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
        team = self.team
        filter = Filter(request=request, team=self.team)

        assert request.user.is_authenticated

        is_csv_request = self.request.accepted_renderer.format == "csv"
        if is_csv_request:
            filter = filter.shallow_clone({LIMIT: CSV_EXPORT_LIMIT, OFFSET: 0})
        elif not filter.limit:
            filter = filter.shallow_clone({LIMIT: DEFAULT_PAGE_LIMIT})

        if posthoganalytics.feature_enabled(
            "load-person-fields-from-clickhouse",
            request.user.distinct_id,
            person_properties={"email": request.user.email},
        ):
            person_query = PersonQuery(
                filter,
                team.pk,
                extra_fields=[
                    "created_at",
                    "properties",
                    "is_identified",
                ],
                include_distinct_ids=True,
            )
            paginated_query, paginated_params = person_query.get_query(paginate=True, filter_future_persons=True)
            actors = insight_sync_execute(
                paginated_query,
                {**paginated_params, **filter.hogql_context.values},
                filter=filter,
                query_type="person_list",
                team_id=team.pk,
            )
            persons = []
            for p in actors:
                person = Person(
                    uuid=p[0],
                    created_at=p[1],
                    is_identified=p[2],
                    properties=json.loads(p[3]),
                )
                person._distinct_ids = p[4]
                persons.append(person)

            serialized_actors = serialize_people(team, data=persons)
            _should_paginate = len(serialized_actors) >= filter.limit
        else:
            person_query = PersonQuery(filter, team.pk)
            paginated_query, paginated_params = person_query.get_query(paginate=True, filter_future_persons=True)

            raw_paginated_result = insight_sync_execute(
                paginated_query,
                {**paginated_params, **filter.hogql_context.values},
                filter=filter,
                query_type="person_list",
                team_id=team.pk,
            )
            actor_ids = [row[0] for row in raw_paginated_result]
            _, serialized_actors = get_people(team, actor_ids)
            _should_paginate = len(actor_ids) >= filter.limit

        # If the undocumented include_total param is set to true, we'll return the total count of people
        # This is extra time and DB load, so we only do this when necessary, which is in PostHog 3000 navigation
        # TODO: Use a more scalable solution before PostHog 3000 navigation is released, and remove this param
        total_count: Optional[int] = None
        if "include_total" in request.GET:
            total_query, total_params = person_query.get_query(paginate=False, filter_future_persons=True)
            total_query_aggregated = f"SELECT count() FROM ({total_query})"
            raw_paginated_result = insight_sync_execute(
                total_query_aggregated,
                {**total_params, **filter.hogql_context.values},
                filter=filter,
                query_type="person_list_total",
                team_id=team.pk,
            )
            total_count = raw_paginated_result[0][0]

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
        parameters=[
            OpenApiParameter(
                "delete_events",
                OpenApiTypes.BOOL,
                description="If true, a task to delete all events associated with this person will be created and queued. The task does not run immediately and instead is batched together and at 5AM UTC every Sunday (controlled by environment variable CLEAR_CLICKHOUSE_REMOVED_DATA_SCHEDULE_CRON)",
                default=False,
            ),
        ],
    )
    def destroy(self, request: request.Request, pk=None, **kwargs):  # type: ignore
        try:
            person = self.get_object()
            person_id = person.id
            delete_person(person=person)
            self.perform_destroy(person)
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team_id,
                user=cast(User, request.user),
                item_id=person_id,
                scope="Person",
                activity="deleted",
                detail=Detail(name=str(person.uuid)),
            )
            # Once the person is deleted, queue deletion of associated data, if that was requested
            if "delete_events" in request.GET:
                AsyncDeletion.objects.bulk_create(
                    [
                        AsyncDeletion(
                            deletion_type=DeletionType.Person,
                            team_id=self.team_id,
                            key=str(person.uuid),
                            created_by=cast(User, self.request.user),
                        )
                    ],
                    ignore_conflicts=True,
                )
            return response.Response(status=202)
        except Person.DoesNotExist:
            raise NotFound(detail="Person not found.")

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs) -> response.Response:
        key = request.GET.get("key")
        value = request.GET.get("value")
        flattened = []
        if key:
            result = self._get_person_property_values_for_key(key, value)

            for value, count in result:
                try:
                    # Try loading as json for dicts or arrays
                    flattened.append(
                        {
                            "name": convert_property_value(json.loads(value)),  # type: ignore
                            "count": count,
                        }
                    )
                except json.decoder.JSONDecodeError:
                    flattened.append({"name": convert_property_value(value), "count": count})
        return response.Response(flattened)

    @timed("get_person_property_values_for_key_timer")
    def _get_person_property_values_for_key(self, key, value):
        try:
            result = get_person_property_values_for_key(key, self.team, value)
            statsd.incr(
                "get_person_property_values_for_key_success",
                tags={"team_id": self.team.id},
            )
        except Exception as e:
            statsd.incr(
                "get_person_property_values_for_key_error",
                tags={
                    "error": str(e),
                    "key": key,
                    "value": value,
                    "team_id": self.team.id,
                },
            )
            raise e

        return result

    @action(methods=["POST"], detail=True)
    def split(self, request: request.Request, pk=None, **kwargs) -> response.Response:
        person: Person = self.get_object()
        distinct_ids = person.distinct_ids

        split_person.delay(person.id, request.data.get("main_distinct_id", None), None)

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=request.user,  # type: ignore
            item_id=person.id,
            scope="Person",
            activity="split_person",
            detail=Detail(
                name=str(person.uuid),
                changes=[
                    Change(
                        type="Person",
                        action="split",
                        after={"distinct_ids": distinct_ids},
                    )
                ],
            ),
        )

        return response.Response({"success": True}, status=201)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "key",
                OpenApiTypes.STR,
                description="Specify the property key",
                required=True,
            ),
            OpenApiParameter(
                "value",
                OpenApiTypes.ANY,
                description="Specify the property value",
                required=True,
            ),
        ]
    )
    @action(methods=["POST"], detail=True)
    def update_property(self, request: request.Request, pk=None, **kwargs) -> response.Response:
        if request.data.get("value") is None:
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
        self._set_properties({request.data["key"]: request.data["value"]}, request.user)
        return Response(status=202)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "$unset",
                OpenApiTypes.STR,
                description="Specify the property key to delete",
                required=True,
            ),
        ]
    )
    @action(methods=["POST"], detail=True)
    def delete_property(self, request: request.Request, pk=None, **kwargs) -> response.Response:
        person: Person = get_pk_or_uuid(Person.objects.filter(team_id=self.team_id), pk).get()

        capture_internal(
            distinct_id=person.distinct_ids[0],
            ip=None,
            site_url=None,
            token=self.team.api_token,
            now=datetime.now(),
            sent_at=None,
            event={
                "event": "$delete_person_property",
                "properties": {"$unset": [request.data["$unset"]]},
                "distinct_id": person.distinct_ids[0],
                "timestamp": datetime.now().isoformat(),
            },
        )

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=request.user,  # type: ignore
            item_id=person.id,
            scope="Person",
            activity="delete_property",
            detail=Detail(name=str(person.uuid), changes=[Change(type="Person", action="changed")]),
        )

        return response.Response({"success": True}, status=201)

    @action(methods=["GET"], detail=False)
    def cohorts(self, request: request.Request) -> response.Response:
        from posthog.api.cohort import CohortSerializer

        team = cast(User, request.user).team
        if not team:
            return response.Response(
                {
                    "message": "Could not retrieve team",
                    "detail": "Could not validate team associated with user",
                },
                status=400,
            )

        person = get_pk_or_uuid(self.get_queryset(), request.GET["person_id"]).get()
        cohort_ids = get_all_cohort_ids_by_person_uuid(person.uuid, team.pk)

        cohorts = Cohort.objects.filter(pk__in=cohort_ids, deleted=False)

        return response.Response({"results": CohortSerializer(cohorts, many=True).data})

    @action(methods=["GET"], url_path="activity", detail=False)
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="Person", team_id=self.team_id, limit=limit, page=page)
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True)
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
            item_id=item_id,
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
        self._set_properties(request.data["properties"], request.user)
        return Response(status=202)

    @extend_schema(exclude=True)
    def create(self, *args, **kwargs):
        raise MethodNotAllowed(
            method="POST",
            detail="Creating persons via this API is not allowed. Please create persons by sending an $identify event. See https://posthog.com/docs/integrate/identifying-user for details.",
        )

    def _set_properties(self, properties, user):
        instance = self.get_object()
        capture_internal(
            distinct_id=instance.distinct_ids[0],
            ip=None,
            site_url=None,
            token=instance.team.api_token,
            now=datetime.now(),
            sent_at=None,
            event={
                "event": "$set",
                "properties": {"$set": properties},
                "distinct_id": instance.distinct_ids[0],
                "timestamp": datetime.now().isoformat(),
            },
        )

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=user,
            item_id=instance.pk,
            scope="Person",
            activity="updated",
            detail=Detail(changes=[Change(type="Person", action="changed", field="properties")]),
        )

    # PRAGMA: Methods for getting Persons via clickhouse queries
    def _respond_with_cached_results(self, results_package: Dict[str, Tuple[List, Optional[str], Optional[str], int]]):
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

    @action(methods=["GET", "POST"], detail=False)
    def funnel(self, request: request.Request, **kwargs) -> response.Response:
        if request.user.is_anonymous or not self.team:
            return response.Response(data=[])

        return self._respond_with_cached_results(self.calculate_funnel_persons(request))

    @cached_by_filters
    def calculate_funnel_persons(
        self, request: request.Request
    ) -> Dict[str, Tuple[List, Optional[str], Optional[str], int]]:
        filter = Filter(request=request, data={"insight": INSIGHT_FUNNELS}, team=self.team)
        filter = prepare_actor_query_filter(filter)
        funnel_actor_class = get_funnel_actor_class(filter)

        actors, serialized_actors, raw_count = funnel_actor_class(filter, self.team).get_actors()
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

    @action(methods=["GET", "POST"], detail=False)
    def path(self, request: request.Request, **kwargs) -> response.Response:
        if request.user.is_anonymous or not self.team:
            return response.Response(data=[])

        return self._respond_with_cached_results(self.calculate_path_persons(request))

    @cached_by_filters
    def calculate_path_persons(
        self, request: request.Request
    ) -> Dict[str, Tuple[List, Optional[str], Optional[str], int]]:
        filter = PathFilter(request=request, data={"insight": INSIGHT_PATHS}, team=self.team)
        filter = prepare_actor_query_filter(filter)

        funnel_filter = None
        funnel_filter_data = request.GET.get("funnel_filter") or request.data.get("funnel_filter")
        if funnel_filter_data:
            if isinstance(funnel_filter_data, str):
                funnel_filter_data = json.loads(funnel_filter_data)
            funnel_filter = Filter(data={"insight": INSIGHT_FUNNELS, **funnel_filter_data}, team=self.team)

        actors, serialized_actors, raw_count = PathsActors(filter, self.team, funnel_filter=funnel_filter).get_actors()
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

    @action(methods=["GET"], detail=False)
    def trends(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        if request.user.is_anonymous or not self.team:
            return response.Response(data=[])

        return self._respond_with_cached_results(self.calculate_trends_persons(request))

    @cached_by_filters
    def calculate_trends_persons(
        self, request: request.Request
    ) -> Dict[str, Tuple[List, Optional[str], Optional[str], int]]:
        filter = Filter(request=request, team=self.team)
        filter = prepare_actor_query_filter(filter)
        entity = get_target_entity(filter)

        actors, serialized_actors, raw_count = TrendsActors(self.team, entity, filter).get_actors()
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

        filter = LifecycleFilter(request=request, data=request.GET.dict(), team=self.team)
        filter = prepare_actor_query_filter(filter)

        people = self.lifecycle_class().get_people(
            filter=filter,
            team=team,
        )
        next_url = paginated_result(request, len(people), filter.offset, filter.limit)
        return response.Response({"results": [{"people": people, "count": len(people)}], "next": next_url})

    @action(methods=["GET"], detail=False)
    def retention(self, request: request.Request) -> response.Response:
        team = cast(User, request.user).team
        if not team:
            return response.Response(
                {
                    "message": "Could not retrieve team",
                    "detail": "Could not validate team associated with user",
                },
                status=400,
            )
        filter = RetentionFilter(request=request, team=team)
        filter = prepare_actor_query_filter(filter)
        base_uri = request.build_absolute_uri("/")

        people, raw_count = self.retention_class(base_uri=base_uri).actors_in_period(filter, team)

        next_url = paginated_result(request, raw_count, filter.offset, filter.limit)

        return response.Response(
            {
                "result": people,
                "next": next_url,
                "missing_persons": raw_count - len(people),
            }
        )

    @action(methods=["GET"], detail=False)
    def stickiness(self, request: request.Request) -> response.Response:
        team = cast(User, request.user).team
        if not team:
            return response.Response(
                {
                    "message": "Could not retrieve team",
                    "detail": "Could not validate team associated with user",
                },
                status=400,
            )
        filter = StickinessFilter(request=request, team=team, get_earliest_timestamp=get_earliest_timestamp)
        filter = prepare_actor_query_filter(filter)

        target_entity = get_target_entity(filter)

        people = self.stickiness_class().people(target_entity, filter, team, request)
        next_url = paginated_result(request, len(people), filter.offset, filter.limit)
        return response.Response({"results": [{"people": people, "count": len(people)}], "next": next_url})


def paginated_result(
    request: request.Request,
    count: int,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> Optional[str]:
    return format_paginated_url(request, offset, limit) if count >= limit else None


T = TypeVar("T", Filter, PathFilter, RetentionFilter, LifecycleFilter, StickinessFilter)


def prepare_actor_query_filter(filter: T) -> T:
    if not filter.limit:
        filter = filter.shallow_clone({LIMIT: DEFAULT_PAGE_LIMIT})

    search = getattr(filter, "search", None)
    if not search:
        return filter

    group_properties_filter_group = []
    if hasattr(filter, "aggregation_group_type_index"):
        group_properties_filter_group += [
            {
                "key": "name",
                "value": search,
                "type": "group",
                "group_type_index": filter.aggregation_group_type_index,  # type: ignore
                "operator": "icontains",
            },
            {
                "key": "slug",
                "value": search,
                "type": "group",
                "group_type_index": filter.aggregation_group_type_index,  # type: ignore
                "operator": "icontains",
            },
        ]

    new_group = {
        "type": "OR",
        "values": [
            {
                "key": "email",
                "type": "person",
                "value": search,
                "operator": "icontains",
            },
            {"key": "name", "type": "person", "value": search, "operator": "icontains"},
            {
                "key": "distinct_id",
                "type": "event",
                "value": search,
                "operator": "icontains",
            },
        ]
        + group_properties_filter_group,
    }
    prop_group = (
        {"type": "AND", "values": [new_group, filter.property_groups.to_dict()]}
        if filter.property_groups.to_dict()
        else new_group
    )

    return filter.shallow_clone({"properties": prop_group, "search": None})


class LegacyPersonViewSet(PersonViewSet):
    legacy_team_compatibility = True
