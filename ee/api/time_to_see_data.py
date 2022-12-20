from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.permissions import IsStaffUser


class TimeToSeeDataViewSet(viewsets.ViewSet):
    permission_classes = [IsStaffUser]

    @action(methods=["POST"], detail=False)
    def sessions(self, request):
        return Response({})
