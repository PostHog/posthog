from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from posthog.api.cohort import CohortSerializer
from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.models import FeatureFlag, Team
from posthog.models.cohort import Cohort, CohortOrEmpty
from posthog.models.filters.filter import Filter


class OrganizationFeatureFlagView(
    TeamAndOrgViewSetMixin,
    viewsets.ViewSet,
    mixins.RetrieveModelMixin,
):
    scope_object = "INTERNAL"
    """
    Retrieves all feature flags for a given organization and key.
    """

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
                "created_by": UserBasicSerializer(flag.created_by).data
                if hasattr(flag, "created_by") and flag.created_by
                else None,
                "filters": flag.get_filters(),
                "created_at": flag.created_at,
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

        # Fetch the flag to copy
        try:
            flag_to_copy = FeatureFlag.objects.get(key=feature_flag_key, team__project_id=from_project)
        except FeatureFlag.DoesNotExist:
            return Response({"error": "Feature flag to copy does not exist."}, status=status.HTTP_400_BAD_REQUEST)

        # Check if the user is allowed to edit the flag using new access control
        from posthog.rbac.user_access_control import UserAccessControl, access_level_satisfied_for_resource

        user_access_control = UserAccessControl(request.user, flag_to_copy.team)
        user_access_level = user_access_control.get_user_access_level(flag_to_copy)

        if not user_access_level or not access_level_satisfied_for_resource(
            "feature_flag", user_access_level, "editor"
        ):
            return Response(
                {"error": "You do not have permission to copy this flag."}, status=status.HTTP_403_FORBIDDEN
            )

        successful_projects = []
        failed_projects = []

        for target_project_id in target_project_ids:
            # Target project does not exist
            target_team = Team.objects.filter(project_id=target_project_id).first()
            if target_team is None:
                failed_projects.append(
                    {
                        "project_id": target_project_id,
                        "errors": "Target project does not exist.",
                    }
                )
                continue

            # get all linked cohorts, sorted by creation order
            seen_cohorts_cache: dict[int, CohortOrEmpty] = {}
            sorted_cohort_ids = flag_to_copy.get_cohort_ids(
                seen_cohorts_cache=seen_cohorts_cache, sort_by_topological_order=True
            )

            # destination cohort id is different from original cohort id - create mapping
            name_to_dest_cohort_id: dict[str, int] = {}
            # create cohorts in the destination project
            if len(sorted_cohort_ids):
                for cohort_id in sorted_cohort_ids:
                    original_cohort = seen_cohorts_cache[cohort_id]

                    if not original_cohort:
                        continue

                    # search in destination project by name
                    destination_cohort = Cohort.objects.filter(
                        name=original_cohort.name, team__project_id=target_project_id, deleted=False
                    ).first()

                    # create new cohort in the destination project
                    if not destination_cohort:
                        prop_group = Filter(
                            data={"properties": original_cohort.properties.to_dict(), "is_simplified": True}
                        ).property_groups

                        for prop in prop_group.flat:
                            if prop.type == "cohort" and not isinstance(prop.value, list):
                                try:
                                    original_child_cohort_id = int(prop.value)
                                    original_child_cohort = seen_cohorts_cache[original_child_cohort_id]

                                    if not original_child_cohort:
                                        continue
                                    prop.value = name_to_dest_cohort_id[original_child_cohort.name]
                                except (ValueError, TypeError):
                                    continue

                        destination_cohort_serializer = CohortSerializer(
                            data={
                                "team": target_team,
                                "name": original_cohort.name,
                                "groups": [],
                                "filters": {"properties": prop_group.to_dict()},
                                "description": original_cohort.description,
                                "is_static": original_cohort.is_static,
                            },
                            context={
                                "request": request,
                                "team_id": target_team.id,
                            },
                        )
                        destination_cohort_serializer.is_valid(raise_exception=True)
                        destination_cohort = destination_cohort_serializer.save()

                    if destination_cohort is not None:
                        name_to_dest_cohort_id[original_cohort.name] = destination_cohort.id

            # reference correct destination cohort ids in the flag
            for group in flag_to_copy.conditions:
                props = group.get("properties", [])
                for prop in props:
                    if isinstance(prop, dict) and prop.get("type") == "cohort":
                        try:
                            original_cohort_id = int(prop["value"])
                            original_cohort_ref = seen_cohorts_cache[original_cohort_id]
                            if not original_cohort_ref:
                                continue
                            cohort_name = original_cohort_ref.name
                            prop["value"] = name_to_dest_cohort_id[cohort_name]
                        except (ValueError, TypeError):
                            continue

            flag_data = {
                "key": flag_to_copy.key,
                "name": flag_to_copy.name,
                "filters": flag_to_copy.get_filters(),
                "active": flag_to_copy.active,
                "rollout_percentage": flag_to_copy.rollout_percentage,
                "ensure_experience_continuity": flag_to_copy.ensure_experience_continuity,
                "deleted": False,
                "evaluation_runtime": flag_to_copy.evaluation_runtime,
            }
            existing_flag = FeatureFlag.objects.filter(
                key=feature_flag_key, team__project_id=target_project_id, deleted=False
            ).first()

            context = {
                "request": request,
                "team_id": target_project_id,
                "project_id": target_project_id,
            }

            # Set method to PATCH for updates, POST for new creations
            # This ensures proper validation scoping for feature flag creation
            if existing_flag:
                request.method = "PATCH"
                feature_flag_serializer = FeatureFlagSerializer(
                    existing_flag, data=flag_data, partial=True, context=context
                )
            # Create new flag
            else:
                request.method = "POST"
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
