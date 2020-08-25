from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.queries.clickhouse_sessions import ClickhouseSessions

# NOTE: bad django practice but /ee specifically depends on /posthog so it should be fine
from posthog.api.event import EventSerializer
from posthog.models.filter import Filter


class ClickhouseEvents(viewsets.ViewSet):
    serializer_class = EventSerializer

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
    def sessions(self, request: Request) -> Response:
        team = self.request.user.team_set.get()
        session_type = request.GET.get("session", None)
        result = ClickhouseSessions().run(Filter(request=request), team, session_type=session_type)
        return Response(result)
