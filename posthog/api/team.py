from django.db.models import QuerySet
from rest_framework import viewsets, mixins, exceptions, response, status
from posthog.models import User, Team
from posthog.api.user import UserSerializer


class TeamUserViewSet(
    mixins.DestroyModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
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

        instance = self.get_object()

        if instance == request.user:
            raise exceptions.ValidationError({"detail": "Cannot delete yourself."})

        self.perform_destroy(instance)
        return response.Response(status=status.HTTP_204_NO_CONTENT)
