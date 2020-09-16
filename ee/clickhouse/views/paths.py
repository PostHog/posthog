from django.db import connection
from rest_framework import request, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ee.clickhouse.queries.clickhouse_paths import ClickhousePaths
from posthog.api.paths import PathsViewSet
from posthog.models import Filter
from posthog.utils import request_to_date_query


# At the moment, paths don't support users changing distinct_ids midway through.
# See: https://github.com/PostHog/posthog/issues/185
class ClickhousePathsViewSet(PathsViewSet):
    @action(methods=["GET"], detail=False)
    def elements(self, request: request.Request):
        return []

    # FIXME: Timestamp is timezone aware timestamp, date range uses naive date.
    # To avoid unexpected results should convert date range to timestamps with timezone.
    def list(self, request):
        team = request.user.team_set.get()
        date_query = request_to_date_query(request.GET, exact=False)
        filter = Filter(request=request)
        start_point = request.GET.get("start")
        request_type = request.GET.get("type", None)
        resp = ClickhousePaths().run(
            filter=filter, start_point=start_point, date_query=date_query, request_type=request_type, team=team
        )
        return Response(resp)
