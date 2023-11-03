from rest_framework.views import APIView
from posthog.models import FeatureFlag
from posthog.models.organization import Organization
from rest_framework.response import Response
from posthog.permissions import OrganizationMemberPermissions
from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers


class OrganizationFeatureFlagView(APIView):
    """
    Retrieves all feature flags for a given organization and key.
    """

    basename = "org_feature_flags"
    permission_classes = [IsAuthenticated, OrganizationMemberPermissions]

    def initial(self, request, *args, **kwargs):
        # Organization needs to be set before permissions are checked
        try:
            self.organization = Organization.objects.get(id=kwargs.get("organization_id"))
        except Organization.DoesNotExist:
            raise serializers.ValidationError("Filters are not valid (can only use group properties)")

        super().initial(request, *args, **kwargs)

    def get(self, request, organization_id, feature_flag_key):

        organization = Organization.objects.get(id=organization_id)
        teams = organization.teams.all()

        flags = FeatureFlag.objects.filter(key=feature_flag_key, team_id__in=[team.id for team in teams])
        flags_data = [{"team_id": flag.team_id, "active": flag.active} for flag in flags]

        return Response(flags_data)
