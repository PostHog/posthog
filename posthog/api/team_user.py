import posthoganalytics
from django.db.models import QuerySet
from rest_framework import exceptions, mixins, response, status, viewsets

from posthog.api.user import UserSerializer
from posthog.models import Team, User


class TeamUserViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = UserSerializer
    queryset = User.objects.none()
    lookup_field = "distinct_id"

    def get_queryset(self) -> QuerySet:
        team: Team = self.request.user.team
        return team.users.all()
