from rest_framework import status, viewsets
from rest_framework.response import Response

# NOTE: bad django practice but /ee specifically depends on /posthog so it should be fine
from posthog.api.person import PersonSerializer


class ClickhousePerson(viewsets.ViewSet):
    serializer_class = PersonSerializer

    def list(self, request):
        # TODO: implement get list of people
        return Response([])

    def create(self, request):
        # TODO: implement create person
        return Response([])

    def retrieve(self, request, pk=None):
        # TODO: implement retrieve person by id
        return Response([])
