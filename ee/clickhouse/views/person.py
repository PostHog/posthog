import json
from typing import List

from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.cohort import format_filter_query
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
from posthog.models.cohort import Cohort
from posthog.models.team import Team


class ClickhousePerson(PersonViewSet):
    def _ch_filter_request(self, request: Request, team: Team) -> List:
        result = []

        all_filters = ""
        params = {"offset": 0, "team_id": team.pk}
        category = request.query_params.get("category")
        if category == "identified":
            all_filters += "AND is_identified = 1 "
        elif category == "anonymous":
            all_filters += "AND is_identified = 0 "

        if request.GET.get("search"):
            parts = request.GET["search"].split(" ")
            contains = []
            for idx, part in enumerate(parts):
                if ":" in part:
                    key_query_filter = """
                    AND person_id IN (
                        SELECT id FROM persons_properties_up_to_date_view WHERE key = %(person_{idx})s
                    ) 
                    """.format(
                        idx=idx
                    )
                    all_filters += key_query_filter
                    params = {**params, "person_{idx}".format(idx=idx): part.split(":")[1]}
                else:
                    contains.append(part)
            for idx, search in enumerate(contains):
                search_query_filter = """
                AND person_id IN (
                    SELECT id FROM person WHERE properties LIKE %({arg})s AND team_id = %(team_id)s
                ) OR person_id IN (
                    SELECT person_id FROM person_distinct_id WHERE distinct_id LIKE %({arg})s AND team_id = %(team_id)s
                )
                """.format(
                    arg="search_{idx}".format(idx=idx)
                )
                all_filters += search_query_filter
                params = {**params, "search_{idx}".format(idx=idx): "%{}%".format(search)}

        if request.GET.get("cohort"):
            cohort_id = request.GET["cohort"]
            cohort = Cohort.objects.get(pk=cohort_id)
            cohort_query, cohort_params = format_filter_query(cohort)
            cohort_query_filter = """
            AND person_id IN ( 
                SELECT person_id FROM person_distinct_id WHERE distinct_id IN (
                    {clause}
                )
            ) """.format(
                clause=cohort_query
            )
            all_filters += cohort_query_filter
            params = {**params, **cohort_params}

        # if request.GET.get("properties"):
        #     pass

        if request.GET.get("id"):
            people = request.GET["id"].split(",")
            result = sync_execute(PEOPLE_SQL.format(content_sql=people), {"offset": 0})
        else:
            result = sync_execute(PEOPLE_BY_TEAM_SQL.format(filters=all_filters), params,)

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

        team = self.request.user.team
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

        team = self.request.user.team
        qres = sync_execute(GET_PERSON_TOP_PROPERTIES, {"limit": 10, "team_id": team.pk})

        return Response([{"name": element[0], "count": element[1]} for element in qres])
