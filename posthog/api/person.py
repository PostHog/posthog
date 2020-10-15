import json
import warnings
from typing import Any, Dict, List

from django.core.cache import cache
from django.db.models import Count, Func, Prefetch, Q, QuerySet
from django_filters import rest_framework as filters
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers  # type: ignore

from posthog.models import Event, Filter, Person, Team
from posthog.utils import convert_property_value

from .base import CursorPagination as BaseCursorPagination


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
        ]

    def get_name(self, person: Person) -> str:
        if person.properties.get("email"):
            return person.properties["email"]
        if len(person.distinct_ids) > 0:
            return person.distinct_ids[-1]
        return person.pk


class CursorPagination(BaseCursorPagination):
    ordering = "-id"
    page_size = 100


class PersonFilter(filters.FilterSet):
    email = filters.CharFilter(field_name="properties__email")
    distinct_id = filters.CharFilter(field_name="persondistinctid__distinct_id")
    key_identifier = filters.CharFilter(method="key_identifier_filter")

    def key_identifier_filter(self, queryset, attr, *args, **kwargs):
        """
        Filters persons by email or distinct ID
        """
        return queryset.filter(Q(persondistinctid__distinct_id=args[0]) | Q(properties__email=args[0]))


class PersonViewSet(viewsets.ModelViewSet):
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (csvrenderers.PaginatedCSVRenderer,)
    queryset = Person.objects.all()
    serializer_class = PersonSerializer
    pagination_class = CursorPagination
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = PersonFilter

    def paginate_queryset(self, queryset):
        if self.request.accepted_renderer.format == "csv" or not self.paginator:
            return None
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    def _filter_request(self, request: request.Request, queryset: QuerySet, team: Team) -> QuerySet:
        if request.GET.get("id"):
            people = request.GET["id"].split(",")
            queryset = queryset.filter(id__in=people)
        if request.GET.get("search"):
            parts = request.GET["search"].split(" ")
            contains = []
            for part in parts:
                if ":" in part:
                    queryset = queryset.filter(properties__has_key=part.split(":")[1])
                else:
                    contains.append(part)
            queryset = queryset.filter(
                Q(properties__icontains=" ".join(contains))
                | Q(persondistinctid__distinct_id__icontains=" ".join(contains))
            ).distinct("id")
        if request.GET.get("cohort"):
            queryset = queryset.filter(cohort__id=request.GET["cohort"])
        if request.GET.get("properties"):
            queryset = queryset.filter(
                Filter(data={"properties": json.loads(request.GET["properties"])}).properties_to_Q(team_id=team.pk)
            )

        queryset_category_pass = None
        category = request.query_params.get("category")
        if category == "identified":
            queryset_category_pass = queryset.filter
        elif category == "anonymous":
            queryset_category_pass = queryset.exclude
        if queryset_category_pass is not None:
            queryset = queryset_category_pass(is_identified=True)

        queryset = queryset.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
        return queryset

    def destroy(self, request: request.Request, pk=None):  # type: ignore
        team = request.user.team
        person = Person.objects.get(team=team, pk=pk)
        events = Event.objects.filter(team=team, distinct_id__in=person.distinct_ids)
        events.delete()
        person.delete()
        return response.Response(status=204)

    def get_queryset(self):
        queryset = super().get_queryset()
        team = self.request.user.team
        queryset = queryset.filter(team=team)
        return self._filter_request(self.request, queryset, team)

    @action(methods=["GET"], detail=False)
    def by_distinct_id(self, request):
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
    def by_email(self, request):
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
    def properties(self, request: request.Request) -> response.Response:
        result = self.get_properties(request)

        return response.Response(result)

    def get_properties(self, request) -> List[Dict[str, Any]]:
        class JsonKeys(Func):
            function = "jsonb_object_keys"

        people = self.get_queryset()
        people = (
            people.annotate(keys=JsonKeys("properties")).values("keys").annotate(count=Count("id")).order_by("-count")
        )
        return [{"name": event["keys"], "count": event["count"]} for event in people]

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request) -> response.Response:
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
    def references(self, request: request.Request) -> response.Response:
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
