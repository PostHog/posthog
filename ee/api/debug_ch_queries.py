import json

from django.core.cache import cache
from rest_framework import viewsets
from rest_framework.response import Response

from posthog.models.team import Team


class DebugCHQueries(viewsets.ViewSet):
    """
    Show recent queries for this user
    """

    def list(self, request):
        return Response(json.loads(cache.get("save_query_{}".format(request.user.pk)) or "[]"))

    def get(self, request):
        return Response([{"hey": "hi"}])
