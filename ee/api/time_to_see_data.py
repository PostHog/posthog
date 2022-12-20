from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.permissions import IsStaffUser
from posthog.queries.query_metrics.sessions import SessionEventsQuerySerializer, get_session_events, get_sessions


class TimeToSeeDataViewSet(viewsets.ViewSet):
    permission_classes = [IsStaffUser]

    @action(methods=["POST"], detail=False)
    def sessions(self, request):
        return Response(get_sessions().data)

    @action(methods=["POST"], detail=False)
    def session_events(self, request):
        query = SessionEventsQuerySerializer(data=request.data)
        query.is_valid(raise_exception=True)
        return Response(get_session_events(query).data)
