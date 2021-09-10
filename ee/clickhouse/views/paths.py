from django.db import connection
from rest_framework import request, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.clickhouse_paths import ClickhousePaths
from ee.clickhouse.sql.events import ELEMENT_TAG_COUNT
from posthog.api.paths import PathsViewSet
from posthog.models import Event, Filter
from posthog.models.filters.path_filter import PathFilter


class ClickhousePathsViewSet(PathsViewSet):
    @action(methods=["GET"], detail=False)
    def elements(self, request: request.Request, **kwargs):

        team = self.team
        response = sync_execute(ELEMENT_TAG_COUNT, {"team_id": team.pk, "limit": 20})

        resp = []
        for row in response:
            resp.append({"name": row[0], "id": row[1], "count": row[2]})

        return Response(resp)

    # FIXME: Timestamp is timezone aware timestamp, date range uses naive date.
    # To avoid unexpected results should convert date range to timestamps with timezone.
    def list(self, request, **kwargs):

        team = self.team
        filter = PathFilter(request=request)
        resp = ClickhousePaths().run(filter=filter, team=team)
        return Response(resp)
