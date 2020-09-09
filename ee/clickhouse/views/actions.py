from rest_framework import status, viewsets
from rest_framework.response import Response

# NOTE: bad django practice but /ee specifically depends on /posthog so it should be fine
from posthog.api.action import ActionSerializer


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
