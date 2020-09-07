import json
from typing import Union

from django.core.cache import cache
from django.db.models import Count, Func, OuterRef, Prefetch, Q, QuerySet, Subquery
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers  # type: ignore

from posthog.models import Cohort, Event, Filter, Person, PersonDistinctId, Team
from posthog.utils import convert_property_value


class TeamSerializer(serializers.ModelSerializer):
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


class PersonViewSet(viewsets.ModelViewSet):
    queryset = Team.objects.all()
    serializer_class = TeamSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        team = self.request.user.team
        queryset = queryset.filter(team=team)
        return self._filter_request(self.request, queryset, team)

    @action(methods=["GET"], detail=False)
    def by_distinct_id(self, request):
        person = self.get_queryset().get(persondistinctid__distinct_id=str(request.GET["distinct_id"]))
        return response.Response(PersonSerializer(person, context={"request": request}).data)

    @action(methods=["GET"], detail=False)
    def properties(self, request: request.Request) -> response.Response:
        class JsonKeys(Func):
            function = "jsonb_object_keys"

        people = self.get_queryset()
        people = (
            people.annotate(keys=JsonKeys("properties")).values("keys").annotate(count=Count("id")).order_by("-count")
        )

        return response.Response([{"name": event["keys"], "count": event["count"]} for event in people])

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
