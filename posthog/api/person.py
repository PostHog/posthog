import json
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Type,
    Union,
    cast,
)

from django.db.models import Count, Func, Q, QuerySet
from django_filters import rest_framework as filters
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.settings import api_settings
from rest_framework.utils.serializer_helpers import ReturnDict
from rest_framework_csv import renderers as csvrenderers

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.person import delete_person
from ee.clickhouse.models.property import get_person_property_values_for_key
from ee.clickhouse.queries.funnels import ClickhouseFunnelActors, ClickhouseFunnelTrendsActors
from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase
from ee.clickhouse.queries.funnels.funnel_correlation_persons import FunnelCorrelationActors
from ee.clickhouse.queries.funnels.funnel_strict_persons import ClickhouseFunnelStrictActors
from ee.clickhouse.queries.funnels.funnel_unordered_persons import ClickhouseFunnelUnorderedActors
from ee.clickhouse.queries.paths import ClickhousePathsActors
from ee.clickhouse.queries.retention.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.queries.stickiness.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.queries.trends.lifecycle import ClickhouseLifecycle
from ee.clickhouse.sql.person import GET_PERSON_PROPERTIES_COUNT
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.utils import format_paginated_url, get_target_entity
from posthog.constants import (
    FUNNEL_CORRELATION_PERSON_LIMIT,
    FUNNEL_CORRELATION_PERSON_OFFSET,
    INSIGHT_FUNNELS,
    INSIGHT_PATHS,
    LIMIT,
    TRENDS_TABLE,
    FunnelVizType,
)
from posthog.decorators import cached_function
from posthog.models import Cohort, Event, Filter, Person, User
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries.base import filter_persons
from posthog.tasks.split_person import split_person
from posthog.utils import (
    convert_property_value,
    flatten,
    format_query_params_absolute_url,
    is_anonymous_id,
    relative_date_parse,
)


class PersonCursorPagination(CursorPagination):
    ordering = "-id"
    page_size = 100


def get_person_name(person: Person) -> str:
    if person.properties.get("email"):
        return person.properties["email"]
    if len(person.distinct_ids) > 0:
        # Prefer non-UUID distinct IDs (presumably from user identification) over UUIDs
        return sorted(person.distinct_ids, key=is_anonymous_id)[0]
    return person.pk


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

    def get_name(self, person: Person) -> str:
        return get_person_name(person)

    def to_representation(self, instance: Person) -> Dict[str, Any]:
        representation = super().to_representation(instance)
        representation["distinct_ids"] = sorted(representation["distinct_ids"], key=is_anonymous_id)
        return representation


class PersonFilter(filters.FilterSet):
    email = filters.CharFilter(field_name="properties__email")
    distinct_id = filters.CharFilter(field_name="persondistinctid__distinct_id")
    key_identifier = filters.CharFilter(method="key_identifier_filter")

    def key_identifier_filter(self, queryset, attr, *args, **kwargs):
        """
        Filters persons by email or distinct ID
        """
        return queryset.filter(Q(persondistinctid__distinct_id=args[0]) | Q(properties__email=args[0]))

    class Meta:
        model = Person
        fields = ["email"]


def should_paginate(results, limit: Union[str, int]) -> bool:
    return len(results) > int(limit) - 1


def get_funnel_actor_class(filter: Filter) -> Callable:
    funnel_actor_class: Type[ClickhouseFunnelBase]
    if filter.funnel_viz_type == FunnelVizType.TRENDS:
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
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (csvrenderers.PaginatedCSVRenderer,)
    queryset = Person.objects.all()
    serializer_class = PersonSerializer
    pagination_class = PersonCursorPagination
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = PersonFilter
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    lifecycle_class = ClickhouseLifecycle
    retention_class = ClickhouseRetention
    stickiness_class = ClickhouseStickiness

    @action(methods=["GET", "POST"], detail=False)
    def funnel(self, request: request.Request, **kwargs) -> response.Response:
        if request.user.is_anonymous or not self.team:
            return response.Response(data=[])

        results_package = self.calculate_funnel_persons(request)

        if not results_package:
            return response.Response(data=[])

        people, next_url, initial_url = results_package["result"]

        return response.Response(
            data={
                "results": [{"people": people, "count": len(people)}],
                "next": next_url,
                "initial": initial_url,
                "is_cached": results_package.get("is_cached"),
                "last_refresh": results_package.get("last_refresh"),
            }
        )

    @cached_function
    def calculate_funnel_persons(
        self, request: request.Request
    ) -> Dict[str, Tuple[list, Optional[str], Optional[str]]]:
        if request.user.is_anonymous or not self.team:
            return {"result": ([], None, None)}

        filter = Filter(request=request, data={"insight": INSIGHT_FUNNELS}, team=self.team)
        if not filter.limit:
            filter = filter.with_data({LIMIT: 100})

        funnel_actor_class = get_funnel_actor_class(filter)

        actors, serialized_actors = funnel_actor_class(filter, self.team).get_actors()
        _should_paginate = should_paginate(actors, filter.limit)
        next_url = format_query_params_absolute_url(request, filter.offset + filter.limit) if _should_paginate else None
        initial_url = format_query_params_absolute_url(request, 0)

        # cached_function expects a dict with the key result
        return {"result": (serialized_actors, next_url, initial_url)}

    @action(methods=["GET", "POST"], url_path="funnel/correlation", detail=False)
    def funnel_correlation(self, request: request.Request, **kwargs) -> response.Response:
        if request.user.is_anonymous or not self.team:
            return response.Response(data=[])

        results_package = self.calculate_funnel_correlation_persons(request)

        if not results_package:
            return response.Response(data=[])

        people, next_url, initial_url = results_package["result"]

        return response.Response(
            data={
                "results": [{"people": people, "count": len(people)}],
                "next": next_url,
                "initial": initial_url,
                "is_cached": results_package.get("is_cached"),
                "last_refresh": results_package.get("last_refresh"),
            }
        )

    @cached_function
    def calculate_funnel_correlation_persons(
        self, request: request.Request
    ) -> Dict[str, Tuple[list, Optional[str], Optional[str]]]:
        if request.user.is_anonymous or not self.team:
            return {"result": ([], None, None)}

        filter = Filter(request=request, data={"insight": INSIGHT_FUNNELS}, team=self.team)
        if not filter.correlation_person_limit:
            filter = filter.with_data({FUNNEL_CORRELATION_PERSON_LIMIT: 100})
        base_uri = request.build_absolute_uri("/")
        actors, serialized_actors = FunnelCorrelationActors(
            filter=filter, team=self.team, base_uri=base_uri
        ).get_actors()
        _should_paginate = should_paginate(actors, filter.correlation_person_limit)

        next_url = (
            format_query_params_absolute_url(
                request,
                filter.correlation_person_offset + filter.correlation_person_limit,
                offset_alias=FUNNEL_CORRELATION_PERSON_OFFSET,
                limit_alias=FUNNEL_CORRELATION_PERSON_LIMIT,
            )
            if _should_paginate
            else None
        )
        initial_url = format_query_params_absolute_url(request, 0)

        # cached_function expects a dict with the key result
        return {"result": (serialized_actors, next_url, initial_url)}

    def paginate_queryset(self, queryset):
        if self.request.accepted_renderer.format == "csv" or not self.paginator:
            return None
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        return filter_persons(self.team_id, request, queryset)

    def destroy(self, request: request.Request, pk=None, **kwargs):  # type: ignore
        try:
            person = Person.objects.get(team=self.team, pk=pk)
            delete_person(
                person.uuid, person.properties, person.is_identified, delete_events=True, team_id=self.team.pk
            )
            person.delete()
            return response.Response(status=204)
        except Person.DoesNotExist:
            raise NotFound(detail="Person not found.")

    def get_queryset(self):
        return self._filter_request(self.request, super().get_queryset())

    @action(methods=["GET"], detail=False)
    def properties(self, request: request.Request, **kwargs) -> response.Response:
        result = self.get_properties(request)

        return response.Response(result)

    def get_properties(self, request: request.Request):
        rows = sync_execute(GET_PERSON_PROPERTIES_COUNT, {"team_id": self.team.pk})
        return [{"name": name, "count": count} for name, count in rows]

    @action(methods=["GET", "POST"], detail=False)
    def path(self, request: request.Request, **kwargs) -> response.Response:
        if request.user.is_anonymous or not self.team:
            return response.Response(data=[])

        results_package = self.calculate_path_persons(request)

        if not results_package:
            return response.Response(data=[])

        people, next_url, initial_url = results_package["result"]

        return response.Response(
            data={
                "results": [{"people": people, "count": len(people)}],
                "next": next_url,
                "initial": initial_url,
                "is_cached": results_package.get("is_cached"),
                "last_refresh": results_package.get("last_refresh"),
            }
        )

    @cached_function
    def calculate_path_persons(self, request: request.Request) -> Dict[str, Tuple[list, Optional[str], Optional[str]]]:
        if request.user.is_anonymous or not self.team:
            return {"result": ([], None, None)}

        filter = PathFilter(request=request, data={"insight": INSIGHT_PATHS}, team=self.team)
        if not filter.limit:
            filter = filter.with_data({LIMIT: 100})

        funnel_filter = None
        funnel_filter_data = request.GET.get("funnel_filter") or request.data.get("funnel_filter")
        if funnel_filter_data:
            if isinstance(funnel_filter_data, str):
                funnel_filter_data = json.loads(funnel_filter_data)
            funnel_filter = Filter(data={"insight": INSIGHT_FUNNELS, **funnel_filter_data}, team=self.team)

        people, serialized_actors = ClickhousePathsActors(filter, self.team, funnel_filter=funnel_filter).get_actors()
        _should_paginate = should_paginate(people, filter.limit)

        next_url = format_query_params_absolute_url(request, filter.offset + filter.limit) if _should_paginate else None
        initial_url = format_query_params_absolute_url(request, 0)

        # cached_function expects a dict with the key result
        return {"result": (serialized_actors, next_url, initial_url)}

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs) -> response.Response:
        key = request.GET.get("key")
        value = request.GET.get("value")
        team = self.team
        flattened = []
        if key:
            result = get_person_property_values_for_key(key, team, value)
            for (value, count) in result:
                try:
                    # Try loading as json for dicts or arrays
                    flattened.append((json.loads(value), count))  # type: ignore
                except json.decoder.JSONDecodeError:
                    flattened.append((value, count))
        return response.Response(
            [{"name": convert_property_value(value), "count": count} for (value, count) in flattened]
        )

    @action(methods=["POST"], detail=True)
    def merge(self, request: request.Request, pk=None, **kwargs) -> response.Response:
        people = Person.objects.filter(team_id=self.team_id, pk__in=request.data.get("ids"))
        person = Person.objects.get(pk=pk, team_id=self.team_id)
        person.merge_people([p for p in people])

        data = PersonSerializer(person).data
        for p in people:
            for distinct_id in p.distinct_ids:
                data["distinct_ids"].append(distinct_id)

        return response.Response(data, status=201)

    @action(methods=["POST"], detail=True)
    def split(self, request: request.Request, pk=None, **kwargs) -> response.Response:
        person = Person.objects.get(pk=pk, team_id=self.team_id)
        split_person.delay(person.id, request.data.get("main_distinct_id", None))
        return response.Response({"success": True}, status=201)

    @action(methods=["GET"], detail=False)
    def lifecycle(self, request: request.Request) -> response.Response:

        team = cast(User, request.user).team
        if not team:
            return response.Response(
                {"message": "Could not retrieve team", "detail": "Could not validate team associated with user"},
                status=400,
            )

        filter = Filter(request=request, team=self.team)
        target_date = request.GET.get("target_date", None)
        if target_date is None:
            return response.Response(
                {"message": "Missing parameter", "detail": "Must include specified date"}, status=400
            )
        target_date_parsed = relative_date_parse(target_date)
        lifecycle_type = request.GET.get("lifecycle_type", None)
        if lifecycle_type is None:
            return response.Response(
                {"message": "Missing parameter", "detail": "Must include lifecycle type"}, status=400
            )

        limit = int(request.GET.get("limit", 100))
        next_url: Optional[str] = request.get_full_path()
        people = self.lifecycle_class().get_people(
            target_date=target_date_parsed,
            filter=filter,
            team_id=team.pk,
            lifecycle_type=lifecycle_type,
            request=request,
            limit=limit,
        )
        next_url = paginated_result(people, request, filter.offset)
        return response.Response({"results": [{"people": people, "count": len(people)}], "next": next_url})

    @action(methods=["GET"], detail=False)
    def retention(self, request: request.Request) -> response.Response:

        display = request.GET.get("display", None)
        team = cast(User, request.user).team
        if not team:
            return response.Response(
                {"message": "Could not retrieve team", "detail": "Could not validate team associated with user"},
                status=400,
            )
        filter = RetentionFilter(request=request, team=team)
        base_uri = request.build_absolute_uri("/")

        if display == TRENDS_TABLE:
            people = self.retention_class(base_uri=base_uri).actors_in_period(filter, team)
        else:
            people = self.retention_class(base_uri=base_uri).actors(filter, team)

        next_url = paginated_result(people, request, filter.offset)

        return response.Response({"result": people, "next": next_url})

    @action(methods=["GET"], detail=False)
    def stickiness(self, request: request.Request) -> response.Response:
        team = cast(User, request.user).team
        if not team:
            return response.Response(
                {"message": "Could not retrieve team", "detail": "Could not validate team associated with user"},
                status=400,
            )
        earliest_timestamp_func = lambda team_id: Event.objects.earliest_timestamp(team_id)
        filter = StickinessFilter(request=request, team=team, get_earliest_timestamp=earliest_timestamp_func)
        if not filter.limit:
            filter = filter.with_data({LIMIT: 100})

        target_entity = get_target_entity(filter)

        people = self.stickiness_class().people(target_entity, filter, team, request)
        next_url = paginated_result(people, request, filter.offset)
        return response.Response({"results": [{"people": people, "count": len(people)}], "next": next_url})

    @action(methods=["GET"], detail=False)
    def cohorts(self, request: request.Request) -> response.Response:
        from posthog.api.cohort import CohortSerializer

        person = self.get_queryset().get(id=str(request.GET["person_id"]))
        cohorts = Cohort.objects.annotate(count=Count("people")).filter(people__id=person.id, deleted=False)

        return response.Response({"results": CohortSerializer(cohorts, many=True).data})


def paginated_result(
    entites: Union[List[Dict[str, Any]], ReturnDict], request: request.Request, offset: int = 0,
) -> Optional[str]:
    return format_paginated_url(request, offset, 100) if len(entites) > 99 else None


class LegacyPersonViewSet(PersonViewSet):
    legacy_team_compatibility = True
