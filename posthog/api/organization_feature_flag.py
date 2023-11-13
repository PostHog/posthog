from posthog.api.routing import StructuredViewSetMixin
from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.models import FeatureFlag, Team
from posthog.permissions import OrganizationMemberPermissions
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework import (
    mixins,
    viewsets,
    status,
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

        flags = FeatureFlag.objects.filter(
            key=feature_flag_key,
            team_id__in=[team.id for team in teams],
            deleted=False,
        )
        flags_data = [
            {
                "flag_id": flag.id,
                "team_id": flag.team_id,
                "active": flag.active,
            }
            for flag in flags
        ]

        return Response(flags_data)

    @action(detail=False, methods=["post"], url_path="copy_flags")
    def copy_flags(self, request, *args, **kwargs):
        body = request.data
        feature_flag_key = body.get("feature_flag_key")
        from_project = body.get("from_project")
        target_project_ids = body.get("target_project_ids")

        if not feature_flag_key or not from_project or not target_project_ids:
            return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            flag_to_copy = FeatureFlag.objects.get(key=feature_flag_key, team_id=from_project)
        except FeatureFlag.DoesNotExist:
            return Response({"error": "Feature flag to copy does not exist."}, status=status.HTTP_400_BAD_REQUEST)

        successful_projects = []
        failed_projects = []

        for target_project_id in target_project_ids:
            # Target project does not exist
            try:
                Team.objects.get(id=target_project_id)
            except ObjectDoesNotExist:
                failed_projects.append(
                    {
                        "project_id": target_project_id,
                        "errors": "Target project does not exist.",
                    }
                )
                continue

            context = {
                "request": request,
                "team_id": target_project_id,
            }
            flag_data = {
                "key": flag_to_copy.key,
                "name": flag_to_copy.name,
                "filters": flag_to_copy.filters,
                "active": flag_to_copy.active,
                "rollout_percentage": flag_to_copy.rollout_percentage,
                "ensure_experience_continuity": flag_to_copy.ensure_experience_continuity,
                "deleted": False,
            }

            existing_flag = FeatureFlag.objects.filter(
                key=feature_flag_key, team_id=target_project_id, deleted=False
            ).first()
            # Update existing flag
            if existing_flag:
                feature_flag_serializer = FeatureFlagSerializer(
                    existing_flag, data=flag_data, partial=True, context=context
                )
            # Create new flag
            else:
                feature_flag_serializer = FeatureFlagSerializer(data=flag_data, context=context)

            try:
                feature_flag_serializer.is_valid(raise_exception=True)
                feature_flag_serializer.save(team_id=target_project_id)
                successful_projects.append(feature_flag_serializer.data)
            except Exception as e:
                failed_projects.append(
                    {
                        "project_id": target_project_id,
                        "errors": str(e) if not feature_flag_serializer.errors else feature_flag_serializer.errors,
                    }
                )

        return Response(
            {"success": successful_projects, "failed": failed_projects},
            status=status.HTTP_200_OK,
        )
