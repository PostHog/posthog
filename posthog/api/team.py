from django.db.models import QuerySet
from rest_framework import exceptions, mixins, response, status, viewsets

from posthog.api.user import UserSerializer
from posthog.models import Team, User


class TeamUserViewSet(mixins.DestroyModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = UserSerializer
    queryset = User.objects.none()
    lookup_field = "distinct_id"

    def get_queryset(self) -> QuerySet:
        team: Team = self.request.user.team_set.get()
        return team.users.all()

    def destroy(self, request, *args, **kwargs):
        """
        Overridden to validate that user is not deleting themselves.
        """

        user_to_delete = self.get_object()

        if user_to_delete == request.user:
            raise exceptions.ValidationError({"detail": "Cannot delete yourself."})
        user_to_delete.team_set.clear()
        user_to_delete.is_active = False
        user_to_delete.save()
        return response.Response(status=status.HTTP_204_NO_CONTENT)
