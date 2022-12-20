from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.permissions import IsStaffUser
from posthog.queries.query_metrics.sessions import get_sessions


class TimeToSeeDataViewSet(viewsets.ViewSet):
    permission_classes = [IsStaffUser]

    @action(methods=["POST", "GET"], detail=False)
    def sessions(self, request):
        return Response(get_sessions())
