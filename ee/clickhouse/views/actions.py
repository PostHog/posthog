from typing import Any

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.queries.clickhouse_trends import ClickhouseTrends

# NOTE: bad django practice but /ee specifically depends on /posthog so it should be fine
from posthog.api.action import ActionSerializer
from posthog.models.filter import Filter


class ClickhouseActions(viewsets.ViewSet):
    serializer_class = ActionSerializer

    def list(self, request):
        # TODO: implement get list of events
        return Response([])

    def create(self, request):
        # TODO: implement create event
        return Response([])

    def retrieve(self, request, pk=None):
        # TODO: implement retrieve event by id
        return Response([])

    @action(methods=["GET"], detail=False)
    def trends(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        team = self.request.user.team_set.get()
        result = ClickhouseTrends().run(Filter(request=request), team)
        return Response(result)
