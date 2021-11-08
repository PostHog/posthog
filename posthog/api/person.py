from typing import Any, Dict, List, Optional, Union, cast

from django.db.models import Count, Func, Prefetch, Q, QuerySet
from django_filters import rest_framework as filters
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.settings import api_settings
from rest_framework.utils.serializer_helpers import ReturnDict
from rest_framework_csv import renderers as csvrenderers

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.utils import format_next_url, get_target_entity
from posthog.constants import TRENDS_TABLE
from posthog.models import Cohort, Event, Filter, Person, User
from posthog.models.filters import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries.base import filter_persons, properties_to_Q
from posthog.queries.lifecycle import LifecycleTrend
from posthog.queries.retention import Retention
from posthog.queries.stickiness import Stickiness
from posthog.tasks.split_person import split_person
from posthog.utils import convert_property_value, get_safe_cache, is_anonymous_id, relative_date_parse


class PersonCursorPagination(CursorPagination):
    ordering = "-id"
    page_size = 100


class PersonSerializer(serializers.HyperlinkedModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = [
            "id",
            "name",
            "distinct_ids",
            "properties",
            "is_identified",
            "created_at",
            "uuid",
        ]

    def get_name(self, person: Person) -> str:
        if person.properties.get("email"):
            return person.properties["email"]
        if len(person.distinct_ids) > 0:
            # Prefer non-UUID distinct IDs (presumably from user identification) over UUIDs
            return sorted(person.distinct_ids, key=is_anonymous_id)[0]
        return person.pk

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
        fields = ["is_identified"]


class PersonViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (csvrenderers.PaginatedCSVRenderer,)
    queryset = Person.objects.all()
    serializer_class = PersonSerializer
    pagination_class = PersonCursorPagination
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = PersonFilter
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    lifecycle_class = LifecycleTrend
    retention_class = Retention
    stickiness_class = Stickiness

    def paginate_queryset(self, queryset):
        if self.request.accepted_renderer.format == "csv" or not self.paginator:
            return None
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        return filter_persons(self.team_id, request, queryset)

    def destroy(self, request: request.Request, pk=None, **kwargs):  # type: ignore
        try:
            person = Person.objects.get(team_id=self.team_id, pk=pk)
            events = Event.objects.filter(team_id=self.team_id, distinct_id__in=person.distinct_ids)
            events.delete()
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

    def get_properties(self, request) -> List[Dict[str, Any]]:
        class JsonKeys(Func):
            function = "jsonb_object_keys"

        people = self.get_queryset()
        people = (
            people.annotate(keys=JsonKeys("properties"))
            .values("keys")
            .annotate(count=Count("id"))
            .order_by("-count", "keys")
        )
        return [{"name": event["keys"], "count": event["count"]} for event in people]

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs) -> response.Response:
        people = self.get_queryset()
        key = "properties__{}".format(request.GET.get("key"))
        people = (
            people.values(key)
            .annotate(count=Count("id"))
            .filter(**{"{}__isnull".format(key): False})
            .order_by("-count")
        )

        if request.GET.get("value"):
            people = people.extra(
                where=["properties ->> %s LIKE %s"], params=[request.GET["key"], "%{}%".format(request.GET["value"])],
            )

        return response.Response(
            [{"name": convert_property_value(event[key]), "count": event["count"]} for event in people[:50]]
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
        filter = RetentionFilter(request=request)

        if display == TRENDS_TABLE:
            people = self.retention_class().people_in_period(filter, team)
        else:
            people = self.retention_class().people(filter, team)

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

        target_entity = get_target_entity(request)

        people = self.stickiness_class().people(target_entity, filter, team, request)
        next_url = paginated_result(people, request, filter.offset)
        return response.Response({"results": [{"people": people, "count": len(people)}], "next": next_url})

    @action(methods=["GET"], detail=False)
    def cohorts(self, request: request.Request) -> response.Response:
        from posthog.api.cohort import CohortSerializer

        person = self.get_queryset().get(id=str(request.GET["person_id"]))
        cohorts = Cohort.objects.annotate(count=Count("people")).filter(people__id=person.id)

        return response.Response({"results": CohortSerializer(cohorts, many=True).data})


def paginated_result(
    entites: Union[List[Dict[str, Any]], ReturnDict], request: request.Request, offset: int = 0,
) -> Optional[str]:
    return format_next_url(request, offset, 100) if len(entites) > 99 else None


class LegacyPersonViewSet(PersonViewSet):
    legacy_team_compatibility = True
