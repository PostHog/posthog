import json
import warnings
from typing import Any, Dict, List, Optional, Union

from django.core.cache import cache
from django.db.models import Count, Func, Prefetch, Q, QuerySet
from django_filters import rest_framework as filters
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.settings import api_settings
from rest_framework.utils.serializer_helpers import ReturnDict
from rest_framework_csv import renderers as csvrenderers

from posthog.api.routing import StructuredViewSetMixin
from posthog.constants import TRENDS_LINEAR, TRENDS_TABLE
from posthog.models import Event, Filter, Person
from posthog.models.filters import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.permissions import ProjectMembershipNecessaryPermissions
from posthog.queries.base import properties_to_Q
from posthog.queries.lifecycle import LifecycleTrend
from posthog.queries.retention import Retention
from posthog.queries.stickiness import Stickiness
from posthog.utils import convert_property_value, relative_date_parse


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
            return person.distinct_ids[-1]
        return person.pk


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
    legacy_team_compatibility = True  # to be moved to a separate Legacy*ViewSet Class

    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (csvrenderers.PaginatedCSVRenderer,)
    queryset = Person.objects.all()
    serializer_class = PersonSerializer
    pagination_class = PersonCursorPagination
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = PersonFilter
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions]

    lifecycle_class = LifecycleTrend
    retention_class = Retention
    stickiness_class = Stickiness

    def paginate_queryset(self, queryset):
        if self.request.accepted_renderer.format == "csv" or not self.paginator:
            return None
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        if request.GET.get("id"):
            ids = request.GET["id"].split(",")
            queryset = queryset.filter(id__in=ids)
        if request.GET.get("uuid"):
            uuids = request.GET["uuid"].split(",")
            queryset = queryset.filter(uuid__in=uuids)
        if request.GET.get("search"):
            parts = request.GET["search"].split(" ")
            contains = []
            for part in parts:
                if ":" in part:
                    matcher, key = part.split(":")
                    if matcher == "has":
                        # Matches for example has:email or has:name
                        queryset = queryset.filter(properties__has_key=key)
                else:
                    contains.append(part)
            queryset = queryset.filter(
                Q(properties__icontains=" ".join(contains))
                | Q(persondistinctid__distinct_id__icontains=" ".join(contains))
            ).distinct("id")
        if request.GET.get("cohort"):
            queryset = queryset.filter(cohort__id=request.GET["cohort"])
        if request.GET.get("properties"):
            filter = Filter(data={"properties": json.loads(request.GET["properties"])})
            queryset = queryset.filter(properties_to_Q(filter.properties, team_id=self.team_id))

        queryset = queryset.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
        return queryset

    def destroy(self, request: request.Request, pk=None, **kwargs):  # type: ignore
        team_id = self.team_id
        person = Person.objects.get(team_id=team_id, pk=pk)
        events = Event.objects.filter(team_id=team_id, distinct_id__in=person.distinct_ids)
        events.delete()
        person.delete()
        return response.Response(status=204)

    def get_queryset(self):
        return self._filter_request(self.request, super().get_queryset())

    @action(methods=["GET"], detail=False)
    def by_distinct_id(self, request, **kwargs):
        """
        DEPRECATED in favor of /api/person/?distinct_id={id}
        """
        warnings.warn(
            "/api/person/by_distinct_id/ endpoint is deprecated; use /api/person/ instead.", DeprecationWarning,
        )
        result = self.get_by_distinct_id(request)
        return response.Response(result)

    def get_by_distinct_id(self, request):
        person = self.get_queryset().get(persondistinctid__distinct_id=str(request.GET["distinct_id"]))
        return PersonSerializer(person).data

    @action(methods=["GET"], detail=False)
    def by_email(self, request, **kwargs):
        """
        DEPRECATED in favor of /api/person/?email={email}
        """
        warnings.warn(
            "/api/person/by_email/ endpoint is deprecated; use /api/person/ instead.", DeprecationWarning,
        )
        result = self.get_by_email(request)
        return response.Response(result)

    def get_by_email(self, request):
        person = self.get_queryset().get(properties__email=str(request.GET["email"]))
        return PersonSerializer(person).data

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

    @action(methods=["GET"], detail=False)
    def references(self, request: request.Request, **kwargs) -> response.Response:
        reference_id = request.GET.get("id", None)
        offset = request.GET.get("offset", None)

        if not reference_id or not offset:
            return response.Response({})

        offset_value = int(offset)
        cached_result = cache.get(reference_id)
        if cached_result:
            return response.Response(
                {
                    "result": cached_result[offset_value : offset_value + 100],
                    "offset": offset_value + 100 if len(cached_result) > offset_value + 100 else None,
                }
            )
        else:
            return response.Response({})

    @action(methods=["POST"], detail=True)
    def merge(self, request: request.Request, pk=None, **kwargs) -> response.Response:
        people = Person.objects.filter(team_id=self.team_id, pk__in=request.data.get("ids"))
        person = Person.objects.get(pk=pk, team_id=self.team_id)
        person.merge_people([p for p in people])

        return response.Response(PersonSerializer(person).data, status=201)

    @action(methods=["GET"], detail=False)
    def lifecycle(self, request: request.Request) -> response.Response:

        team = request.user.team
        if not team:
            return response.Response(
                {"message": "Could not retrieve team", "detail": "Could not validate team associated with user"},
                status=400,
            )

        filter = Filter(request=request)
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
            target_date=target_date_parsed, filter=filter, team_id=team.pk, lifecycle_type=lifecycle_type, limit=limit,
        )
        next_url = paginated_result(people, request, filter.offset)

        return response.Response({"results": [{"people": people, "count": len(people)}], "next": next_url})

    @action(methods=["GET"], detail=False)
    def retention(self, request: request.Request) -> response.Response:

        display = request.GET.get("display", None)
        team = request.user.team
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
        team = request.user.team
        if not team:
            return response.Response(
                {"message": "Could not retrieve team", "detail": "Could not validate team associated with user"},
                status=400,
            )
        earliest_timestamp_func = lambda team_id: Event.objects.earliest_timestamp(team_id)
        filter = StickinessFilter(request=request, team=team, get_earliest_timestamp=earliest_timestamp_func)
        people = self.stickiness_class().people(filter, team)
        next_url = paginated_result(people, request, filter.offset)
        return response.Response({"results": [{"people": people, "count": len(people)}], "next": next_url})


def paginated_result(
    entites: Union[List[Dict[str, Any]], ReturnDict], request: request.Request, offset: int = 0
) -> Optional[str]:
    next_url: Optional[str] = request.get_full_path()
    if len(entites) > 99 and next_url:
        if "offset" in next_url:
            next_url = next_url[1:]
            next_url = next_url.replace("offset=" + str(offset), "offset=" + str(offset + 100))
        else:
            next_url = request.build_absolute_uri(
                "{}{}offset={}".format(next_url, "&" if "?" in next_url else "?", offset + 100)
            )
    else:
        next_url = None
    return next_url
