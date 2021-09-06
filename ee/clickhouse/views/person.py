import json
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

from django.db.models.query import Prefetch, QuerySet
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.person import delete_person
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.queries.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.queries.funnels import ClickhouseFunnelPersons, ClickhouseFunnelTrendsPersons
from ee.clickhouse.queries.trends.lifecycle import ClickhouseLifecycle
from ee.clickhouse.sql.person import GET_LATEST_PERSON_WITH_DISTINCT_IDS_SQL, GET_PERSON_PROPERTIES_COUNT
from posthog.api.person import PersonViewSet
from posthog.api.utils import format_offset_absolute_url
from posthog.constants import FunnelVizType
from posthog.decorators import cached_function
from posthog.exceptions import UnsupportedFeature
from posthog.models import Event, Filter, Person


def filter_persons_ch(team_id: int, request: Request, queryset: QuerySet) -> QuerySet:
    # Keep functionality in sync with posthog/api/person.py
    params: Dict[str, Any] = {"team_id": team_id}
    and_conditions: List[str] = []
    if request.GET.get("id"):
        raise UnsupportedFeature("filtering persons by field `id`")
    if request.GET.get("uuid"):
        params["uuids"] = request.GET["uuid"].split(",")
        and_conditions.append("AND has(%(uuids)s, toString(person.id))")
    if request.GET.get("search"):
        parts = request.GET["search"].split(" ")
        contains = []
        for part_index, part in enumerate(parts):
            if ":" in part:
                matcher, key = part.split(":")
                if matcher == "has":
                    # Matches for example has:email or has:name
                    params[f"has_key_{part_index}"] = key
                    and_conditions.append(f"AND JSONHas(properties, %(has_key_{part_index})s)")
            else:
                contains.append(part)
        if contains:
            params["icontains"] = f'%{" ".join(contains)}%'
            and_conditions.append(
                f"""
                AND (
                    properties ILIKE %(icontains)s
                    OR arrayExists(distinct_id -> ilike(distinct_id, %(icontains)s), distinct_ids)
                )"""
            )
    properties: List[Dict[str, Any]] = json.loads(request.GET["properties"]) if request.GET.get("properties") else []
    if request.GET.get("cohort"):
        properties.append({"type": "cohort", "key": "id", "value": request.GET["cohort"]})
    if properties:
        for property in properties:
            if property.get("type") is None:
                # In this endpoint the default type is "person", not default "event", which we ensure here
                property["type"] = "person"
        filter = Filter(data={"properties": properties})
        filter_query, filter_params = parse_prop_clauses(filter.properties, team_id, is_person_query=True)
        and_conditions.append(filter_query)
        params.update(filter_params)

    if and_conditions:
        final_query = GET_LATEST_PERSON_WITH_DISTINCT_IDS_SQL.format(query=" ".join(and_conditions))
        uuids_found_rows = cast(list, sync_execute(final_query, params))
        uuids_found = [row[0] for row in uuids_found_rows]
        queryset = queryset.filter(uuid__in=uuids_found)

    queryset = queryset.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
    return queryset


class ClickhousePersonViewSet(PersonViewSet):
    lifecycle_class = ClickhouseLifecycle
    retention_class = ClickhouseRetention
    stickiness_class = ClickhouseStickiness

    def _filter_request(self, request: Request, queryset: QuerySet) -> QuerySet:
        return filter_persons_ch(self.team_id, request, queryset)

    @action(methods=["GET", "POST"], detail=False)
    def funnel(self, request: Request, **kwargs) -> Response:
        if request.user.is_anonymous or not request.user.team:
            return Response(data=[])

        results_package = self.calculate_funnel_persons(request)

        if not results_package:
            return Response(data=[])

        people, next_url, initial_url = results_package["result"]

        return Response(
            data={
                "results": [{"people": people, "count": len(people)}],
                "next": next_url,
                "initial": initial_url,
                "is_cached": results_package.get("is_cached"),
                "last_refresh": results_package.get("last_refresh"),
            }
        )

    @cached_function
    def calculate_funnel_persons(self, request: Request) -> Dict[str, Tuple[list, Optional[str], Optional[str]]]:
        if request.user.is_anonymous or not request.user.team:
            return {"result": ([], None, None)}

        team = request.user.team
        filter = Filter(request=request)
        funnel_class: Callable = ClickhouseFunnelPersons

        if filter.funnel_viz_type == FunnelVizType.TRENDS:
            funnel_class = ClickhouseFunnelTrendsPersons

        people, should_paginate = funnel_class(filter, team).run()
        limit = filter.limit if filter.limit else 100
        next_url = format_offset_absolute_url(request, filter.offset + limit) if should_paginate else None
        initial_url = format_offset_absolute_url(request, 0)

        # cached_function expects a dict with the key result
        return {"result": (people, next_url, initial_url)}

    def get_properties(self, request: Request):
        rows = sync_execute(GET_PERSON_PROPERTIES_COUNT, {"team_id": self.team.pk})
        return [{"name": name, "count": count} for name, count in rows]

    def destroy(self, request: Request, pk=None, **kwargs):  # type: ignore
        try:
            person = Person.objects.get(team=self.team, pk=pk)

            events = Event.objects.filter(team=self.team, distinct_id__in=person.distinct_ids)
            events.delete()
            delete_person(
                person.uuid, person.properties, person.is_identified, delete_events=True, team_id=self.team.pk
            )
            person.delete()
            return Response(status=204)
        except Person.DoesNotExist:
            raise NotFound(detail="Person not found.")
