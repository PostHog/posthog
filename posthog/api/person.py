from posthog.models import Event, Team, Person, PersonDistinctId, Cohort, Filter
from posthog.utils import convert_property_value
from rest_framework import serializers, viewsets, response, request
from rest_framework.decorators import action
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers  # type: ignore
from django.db.models import Q, Prefetch, QuerySet, Subquery, OuterRef, Count, Func
from .event import EventSerializer
from typing import Union
from .base import CursorPagination as BaseCursorPagination
import json


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


class PersonViewSet(viewsets.ModelViewSet):
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (
        csvrenderers.PaginatedCSVRenderer,
    )
    queryset = Person.objects.all()
    serializer_class = PersonSerializer
    pagination_class = CursorPagination

    def paginate_queryset(self, queryset):
        if "text/csv" in self.request.accepted_media_type or not self.paginator:
            return None
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    def _filter_request(
        self, request: request.Request, queryset: QuerySet, team: Team
    ) -> QuerySet:
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
            queryset = queryset.filter(properties__icontains=" ".join(contains))
        if request.GET.get("cohort"):
            queryset = queryset.filter(cohort__id=request.GET["cohort"])
        if request.GET.get("properties"):
            queryset = queryset.filter(
                Filter(
                    data={"properties": json.loads(request.GET["properties"])}
                ).properties_to_Q(team_id=team.pk)
            )

        queryset = queryset.prefetch_related(
            Prefetch("persondistinctid_set", to_attr="distinct_ids_cache")
        )
        return queryset

    def destroy(self, request: request.Request, pk=None):  # type: ignore
        team = request.user.team_set.get()
        person = Person.objects.get(team=team, pk=pk)
        events = Event.objects.filter(team=team, distinct_id__in=person.distinct_ids)
        events.delete()
        person.delete()
        return response.Response(status=204)

    def get_queryset(self):
        queryset = super().get_queryset()
        team = self.request.user.team_set.get()
        queryset = queryset.filter(team=team)
        return self._filter_request(self.request, queryset, team)

    @action(methods=["GET"], detail=False)
    def by_distinct_id(self, request):
        person = self.get_queryset().get(
            persondistinctid__distinct_id=str(request.GET["distinct_id"])
        )
        return response.Response(
            PersonSerializer(person, context={"request": request}).data
        )

    @action(methods=["GET"], detail=False)
    def properties(self, request: request.Request) -> response.Response:
        class JsonKeys(Func):
            function = "jsonb_object_keys"

        people = self.get_queryset()
        people = (
            people.annotate(keys=JsonKeys("properties"))
            .values("keys")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        return response.Response(
            [{"name": event["keys"], "count": event["count"]} for event in people]
        )

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
                where=["properties ->> %s LIKE %s"],
                params=[request.GET["key"], "%{}%".format(request.GET["value"])],
            )

        return response.Response(
            [
                {"name": convert_property_value(event[key]), "count": event["count"]}
                for event in people[:50]
            ]
        )
