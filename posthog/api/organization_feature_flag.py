from posthog.api.routing import StructuredViewSetMixin
from posthog.models import FeatureFlag
from posthog.permissions import OrganizationMemberPermissions
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import (
    mixins,
    viewsets,
)


class OrganizationFeatureFlagView(
    viewsets.ViewSet,
    StructuredViewSetMixin,
    mixins.RetrieveModelMixin,
):
    """
    Retrieves all feature flags for a given organization and key.
    """

    permission_classes = [IsAuthenticated, OrganizationMemberPermissions]
    lookup_field = "feature_flag_key"

    def retrieve(self, request, *args, **kwargs):
        feature_flag_key = kwargs.get(self.lookup_field)

        teams = self.organization.teams.all()

        flags = FeatureFlag.objects.filter(key=feature_flag_key, team_id__in=[team.id for team in teams])
        flags_data = [{"team_id": flag.team_id, "active": flag.active} for flag in flags]

        return Response(flags_data)
