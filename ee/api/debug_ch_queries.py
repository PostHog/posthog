import json

from rest_framework import mixins, viewsets
from rest_framework.response import Response

from posthog.utils import get_safe_cache


class DebugCHQueries(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Show recent queries for this user
    """

    def list(self, request):
        return Response(json.loads(get_safe_cache("save_query_{}".format(request.user.pk)) or "[]"))
