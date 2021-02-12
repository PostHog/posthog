import json

from rest_framework import viewsets
from rest_framework.response import Response

from posthog.models.team import Team
from posthog.utils import get_safe_cache


class DebugCHQueries(viewsets.ViewSet):
    """
    Show recent queries for this user
    """

    def list(self, request):
        return Response(json.loads(get_safe_cache("save_query_{}".format(request.user.pk)) or "[]"))

    def get(self, request):
        return Response([{"hey": "hi"}])
