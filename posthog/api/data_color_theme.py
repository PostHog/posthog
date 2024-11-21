from rest_framework import viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin


class DataColorThemeViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
