from typing import List

from django.db.models.expressions import Func
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.person import ClickhousePersonSerializer
from ee.clickhouse.sql.person import (
    GET_PERSON_TOP_PROPERTIES,
    PEOPLE_BY_TEAM_SQL,
    PEOPLE_SQL,
    PEOPLE_THROUGH_DISTINCT_SQL,
)
from ee.clickhouse.util import CH_PERSON_ENDPOINT, endpoint_enabled

# NOTE: bad django practice but /ee specifically depends on /posthog so it should be fine
from posthog.api.person import PersonViewSet
from posthog.models.team import Team


class ClickhousePerson(PersonViewSet):
    def _ch_filter_request(self, request: Request, team: Team) -> List:
        result = []

        queryset_category_pass = ""
        category = request.query_params.get("category")
        if category == "identified":
            queryset_category_pass = "AND is_identified = 1"
        elif category == "anonymous":
            queryset_category_pass = "AND is_identified = 0"

        if request.GET.get("id"):
            people = request.GET["id"].split(",")
            result = sync_execute(PEOPLE_SQL.format(content_sql=people), {"offset": 0})
        else:
            result = sync_execute(
                PEOPLE_BY_TEAM_SQL.format(filters=queryset_category_pass), {"offset": 0, "team_id": team.pk},
            )

        # if request.GET.get("search"):
        #     parts = request.GET["search"].split(" ")
        #     contains = []
        #     for part in parts:
        #         if ":" in part:
        #             queryset = queryset.filter(properties__has_key=part.split(":")[1])
        #         else:
        #             contains.append(part)
        #     queryset = queryset.filter(
        #         Q(properties__icontains=" ".join(contains))
        #         | Q(persondistinctid__distinct_id__icontains=" ".join(contains))
        #     ).distinct("id")
        # if request.GET.get("cohort"):
        #     queryset = queryset.filter(cohort__id=request.GET["cohort"])
        # if request.GET.get("properties"):
        #     queryset = queryset.filter(
        #         Filter(data={"properties": json.loads(request.GET["properties"])}).properties_to_Q(team_id=team.pk)
        #     )

        return result

    def retrieve(self, request, pk=None):

        if not endpoint_enabled(CH_PERSON_ENDPOINT, request.user.distinct_id):
            return super().retrieve(request, pk)

        qres = sync_execute(PEOPLE_SQL.format(content_sql=[pk]), {"offset": 0})
        res = ClickhousePersonSerializer(qres[0]).data if len(qres) > 0 else []
        return Response(res)

    def list(self, request):

        if not endpoint_enabled(CH_PERSON_ENDPOINT, request.user.distinct_id):
            return super().list(request)

        team = self.request.user.team_set.get()
        filtered = self._ch_filter_request(self.request, team)
        results = ClickhousePersonSerializer(filtered, many=True).data
        return Response({"results": results})

    @action(methods=["GET"], detail=False)
    def by_distinct_id(self, request):

        if not endpoint_enabled(CH_PERSON_ENDPOINT, request.user.distinct_id):
            result = super().get_by_distinct_id(request)
            return Response(result)

        distinct_id = str(request.GET["distinct_id"])
        result = sync_execute(PEOPLE_THROUGH_DISTINCT_SQL.format(content_sql=[distinct_id]), {"offset": 0})
        res = ClickhousePersonSerializer(result[0]).data if len(result) > 0 else []
        return Response(res)

    @action(methods=["GET"], detail=False)
    def properties(self, request: Request) -> Response:

        if not endpoint_enabled(CH_PERSON_ENDPOINT, request.user.distinct_id):
            result = super().get_properties(request)
            return Response(result)

        team = self.request.user.team_set.get()
        qres = sync_execute(GET_PERSON_TOP_PROPERTIES, {"limit": 10, "team_id": team.pk})

        return Response([{"name": element[0], "count": element[1]} for element in qres])
