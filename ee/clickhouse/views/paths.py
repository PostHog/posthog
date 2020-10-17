from django.db import connection
from rest_framework import request, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.clickhouse_paths import ClickhousePaths
from ee.clickhouse.sql.events import ELEMENT_TAG_COUNT
from ee.clickhouse.util import CH_PATH_ENDPOINT, endpoint_enabled
from posthog.api.paths import PathsViewSet
from posthog.models import Event, Filter


class ClickhousePathsViewSet(PathsViewSet):
    @action(methods=["GET"], detail=False)
    def elements(self, request: request.Request):

        if not endpoint_enabled(CH_PATH_ENDPOINT, request.user.distinct_id):
            result = super().get_elements(request)
            return Response(result)

        team = request.user.team_set.get()
        response = sync_execute(ELEMENT_TAG_COUNT, {"team_id": team.pk, "limit": 20})

        resp = []
        for row in response:
            resp.append({"name": row[0], "id": row[1], "count": row[2]})

        return Response(resp)

    # FIXME: Timestamp is timezone aware timestamp, date range uses naive date.
    # To avoid unexpected results should convert date range to timestamps with timezone.
    def list(self, request):

        if not endpoint_enabled(CH_PATH_ENDPOINT, request.user.distinct_id):
            result = super().get_list(request)
            return Response(result)

        team = request.user.team_set.get()
        filter = Filter(request=request)
        resp = ClickhousePaths().run(filter=filter, team=team)
        return Response(resp)
